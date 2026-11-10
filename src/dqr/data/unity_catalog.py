"""Unity Catalog setup: storage credential, external location, catalog, schemas.

Plain functions over a Databricks client (a `WorkspaceClient`, or a fake in tests).
Nothing here reads `.env`: the caller loads it into the environment.
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import AzureManagedIdentityRequest

# Every object setup creates carries this comment; teardown touches only those.
MARKER = "Managed by the delta-router dev tool (dqr)"

CREDENTIAL_NAME = "dqr-storage"
LOCATION_NAME = "dqr-tpcds"
CONTAINER = "tpcds"
DEFAULT_CATALOG = "dqr"
SCHEMA_NAMES = ("sf1", "sf10")

REQUIRED_SETTINGS = (
    "UC_ACCESS_CONNECTOR_ID",
    "UC_IDENTITY_RESOURCE_ID",
    "DQR_STORAGE_ACCOUNT",
)


class SettingsError(Exception):
    """A required setting is missing."""


class SetupError(Exception):
    """Setup stopped before creating anything."""


@dataclass(frozen=True)
class Settings:
    access_connector_id: str
    identity_resource_id: str
    storage_account: str
    catalog: str = DEFAULT_CATALOG

    @property
    def location_url(self) -> str:
        return f"abfss://{CONTAINER}@{self.storage_account}.dfs.core.windows.net/"


@dataclass(frozen=True)
class Step:
    """One line of a setup report."""

    kind: str
    name: str
    status: str


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the settings from `env` (default: the process environment).

    Errors name the missing variables and never show a value.
    """
    env = os.environ if env is None else env
    values = {name: env.get(name, "").strip() for name in REQUIRED_SETTINGS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SettingsError(f"missing settings: {', '.join(missing)}")
    return Settings(
        access_connector_id=values["UC_ACCESS_CONNECTOR_ID"],
        identity_resource_id=values["UC_IDENTITY_RESOURCE_ID"],
        storage_account=values["DQR_STORAGE_ACCOUNT"],
        catalog=env.get("DQR_CATALOG", "").strip() or DEFAULT_CATALOG,
    )


@dataclass
class _Item:
    kind: str
    name: str
    found: object | None  # what the client returned, None if the object is absent
    create: Callable[[], object]
    adopt: bool = False  # an existing object is accepted as is (the catalog)


def _find(get: Callable[[str], object], key: str) -> object | None:
    try:
        return get(key)
    except NotFound:
        return None


def setup(client, settings: Settings) -> list[Step]:
    """Create what is missing, in order, and report what happened.

    All lookups run before the first create, so a name clash stops setup cleanly.
    """
    catalog = settings.catalog
    found_catalog = _find(client.catalogs.get, catalog)
    items = [
        _Item(
            "storage credential",
            CREDENTIAL_NAME,
            _find(client.storage_credentials.get, CREDENTIAL_NAME),
            partial(
                client.storage_credentials.create,
                name=CREDENTIAL_NAME,
                azure_managed_identity=AzureManagedIdentityRequest(
                    access_connector_id=settings.access_connector_id,
                    managed_identity_id=settings.identity_resource_id,
                ),
                comment=MARKER,
            ),
        ),
        _Item(
            "external location",
            LOCATION_NAME,
            _find(client.external_locations.get, LOCATION_NAME),
            partial(
                client.external_locations.create,
                name=LOCATION_NAME,
                url=settings.location_url,
                credential_name=CREDENTIAL_NAME,
                comment=MARKER,
            ),
        ),
        _Item(
            "catalog",
            catalog,
            found_catalog,
            partial(client.catalogs.create, name=catalog, comment=MARKER),
            adopt=True,
        ),
    ]
    for schema in SCHEMA_NAMES:
        full_name = f"{catalog}.{schema}"
        items.append(
            _Item(
                "schema",
                full_name,
                # No catalog yet means no schema yet: skip the lookup.
                _find(client.schemas.get, full_name) if found_catalog else None,
                partial(
                    client.schemas.create,
                    name=schema,
                    catalog_name=catalog,
                    comment=MARKER,
                ),
            )
        )

    for item in items:
        if item.found is not None and not item.adopt and not _is_ours(item.found):
            raise SetupError(
                f"{item.kind} {item.name} already exists and was not created by "
                "this tool; nothing was changed"
            )

    report = []
    for item in items:
        if item.found is None:
            item.create()
            status = "created"
        elif _is_ours(item.found):
            status = "exists"
        else:
            status = "exists, not managed"
        report.append(Step(item.kind, item.name, status))
    return report


def _is_ours(found: object) -> bool:
    return getattr(found, "comment", None) == MARKER
