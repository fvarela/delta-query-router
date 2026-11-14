"""Unit tests for the Unity Catalog setup, against a fake Databricks client.

Nothing here calls Databricks. The fake mirrors the method names and arguments of
the real SDK, and raises databricks.sdk.errors.NotFound for missing objects.
"""

from types import SimpleNamespace

import pytest
from databricks.sdk.errors import NotFound

from dqr.data.unity_catalog import (
    MARKER,
    Settings,
    SettingsError,
    SetupError,
    TeardownError,
    load_settings,
    setup,
    teardown,
)

ENV = {
    "UC_ACCESS_CONNECTOR_ID": "connector-id",
    "UC_IDENTITY_RESOURCE_ID": "identity-id",
    "DQR_STORAGE_ACCOUNT": "examplestorage",
}


class _Api:
    """Objects by key, plus the call log shared by every fake API."""

    def __init__(self, calls: list, kind: str):
        self._calls = calls
        self._kind = kind
        self.objects: dict[str, SimpleNamespace] = {}

    def _get(self, key):
        if key not in self.objects:
            raise NotFound(f"{self._kind} {key} does not exist")
        return self.objects[key]

    def _create(self, key, comment, **fields):
        assert key not in self.objects, f"{self._kind} {key} created twice"
        self._calls.append(("create", self._kind, key, {"comment": comment, **fields}))
        self.objects[key] = SimpleNamespace(comment=comment)

    def _delete(self, key, force):
        self._calls.append(("delete", self._kind, key, {"force": force}))
        if key not in self.objects:
            raise NotFound(f"{self._kind} {key} does not exist")
        del self.objects[key]


class _Credentials(_Api):
    def get(self, name):
        return self._get(name)

    def create(self, name, *, azure_managed_identity=None, comment=None):
        self._create(name, comment, azure_managed_identity=azure_managed_identity)

    def delete(self, name, *, force=None):
        self._delete(name, force)


class _Locations(_Api):
    def get(self, name):
        return self._get(name)

    def create(self, name, url, credential_name, *, comment=None):
        self._create(name, comment, url=url, credential_name=credential_name)

    def delete(self, name, *, force=None):
        self._delete(name, force)


class _Catalogs(_Api):
    def get(self, name):
        return self._get(name)

    def create(self, name, *, comment=None):
        self._create(name, comment)

    def delete(self, name, *, force=None):
        self._delete(name, force)


class _Schemas(_Api):
    def get(self, full_name):
        return self._get(full_name)

    def create(self, name, catalog_name, *, comment=None):
        self._create(f"{catalog_name}.{name}", comment)

    def delete(self, full_name, *, force=None):
        self._delete(full_name, force)


class FakeClient:
    def __init__(self):
        self.calls: list = []
        self.storage_credentials = _Credentials(self.calls, "storage credential")
        self.external_locations = _Locations(self.calls, "external location")
        self.catalogs = _Catalogs(self.calls, "catalog")
        self.schemas = _Schemas(self.calls, "schema")

    def created(self):
        return [
            (kind, key) for action, kind, key, _ in self.calls if action == "create"
        ]

    def deleted(self):
        return [
            (kind, key) for action, kind, key, _ in self.calls if action == "delete"
        ]


def make_settings(catalog="dqr"):
    return Settings(
        access_connector_id="connector-id",
        identity_resource_id="identity-id",
        storage_account="examplestorage",
        catalog=catalog,
    )


def summary(report):
    return [(step.kind, step.name, step.status) for step in report]


def test_e1_setup_on_an_empty_metastore_creates_five_objects_in_order():
    client = FakeClient()

    report = setup(client, make_settings())

    assert client.created() == [
        ("storage credential", "dqr-storage"),
        ("external location", "dqr-tpcds"),
        ("catalog", "dqr"),
        ("schema", "dqr.sf1"),
        ("schema", "dqr.sf10"),
    ]
    assert summary(report) == [
        ("storage credential", "dqr-storage", "created"),
        ("external location", "dqr-tpcds", "created"),
        ("catalog", "dqr", "created"),
        ("schema", "dqr.sf1", "created"),
        ("schema", "dqr.sf10", "created"),
    ]
    fields = {key: f for _, _, key, f in client.calls}
    identity = fields["dqr-storage"]["azure_managed_identity"]
    assert identity.access_connector_id == "connector-id"
    assert identity.managed_identity_id == "identity-id"
    location = fields["dqr-tpcds"]
    assert location["url"] == "abfss://tpcds@examplestorage.dfs.core.windows.net/"
    assert location["credential_name"] == "dqr-storage"
    assert all(f["comment"] == MARKER for f in fields.values())
    assert client.deleted() == []


def test_e2_setup_twice_creates_nothing_the_second_time():
    client = FakeClient()
    setup(client, make_settings())
    client.calls.clear()

    report = setup(client, make_settings())

    assert client.calls == []
    assert [step.status for step in report] == ["exists"] * 5


@pytest.mark.parametrize(
    ("api", "key", "comment", "pattern"),
    [
        (
            "storage_credentials",
            "dqr-storage",
            "someone else's",
            r"storage credential.*dqr-storage",
        ),
        ("external_locations", "dqr-tpcds", None, r"external location.*dqr-tpcds"),
        ("schemas", "dqr.sf10", "someone else's", r"schema.*dqr\.sf10"),
    ],
)
def test_e3_a_name_clash_stops_setup_before_any_create(api, key, comment, pattern):
    client = FakeClient()
    client.catalogs.objects["dqr"] = SimpleNamespace(comment=MARKER)
    getattr(client, api).objects[key] = SimpleNamespace(comment=comment)

    with pytest.raises(SetupError, match=pattern):
        setup(client, make_settings())

    assert client.calls == []


def test_e4_an_existing_catalog_is_used_as_is():
    client = FakeClient()
    client.catalogs.objects["existing_catalog"] = SimpleNamespace(comment=None)

    report = setup(client, make_settings(catalog="existing_catalog"))

    assert client.created() == [
        ("storage credential", "dqr-storage"),
        ("external location", "dqr-tpcds"),
        ("schema", "existing_catalog.sf1"),
        ("schema", "existing_catalog.sf10"),
    ]
    assert summary(report)[2] == ("catalog", "existing_catalog", "exists, not managed")
    assert client.deleted() == []


def test_e7_missing_settings_are_named_but_never_their_values():
    env = {"UC_ACCESS_CONNECTOR_ID": "secret-connector", "DQR_STORAGE_ACCOUNT": ""}

    with pytest.raises(SettingsError) as error:
        load_settings(env)

    message = str(error.value)
    assert "UC_IDENTITY_RESOURCE_ID" in message
    assert "DQR_STORAGE_ACCOUNT" in message
    assert "UC_ACCESS_CONNECTOR_ID" not in message
    assert "secret-connector" not in message


def test_e7_catalog_defaults_to_dqr_when_unset_or_empty():
    assert load_settings(ENV).catalog == "dqr"
    assert load_settings({**ENV, "DQR_CATALOG": ""}).catalog == "dqr"
    assert load_settings({**ENV, "DQR_CATALOG": "other"}).catalog == "other"


def test_e7_settings_are_read_from_the_environment_by_default(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DQR_CATALOG", raising=False)

    assert load_settings() == make_settings()


def set_up(catalog="dqr"):
    """A client on which setup has run, with the call log cleared."""
    client = FakeClient()
    setup(client, make_settings(catalog))
    client.calls.clear()
    return client


FULL_TEARDOWN = [
    ("schema", "dqr.sf10"),
    ("schema", "dqr.sf1"),
    ("catalog", "dqr"),
    ("external location", "dqr-tpcds"),
    ("storage credential", "dqr-storage"),
]


def test_e5_teardown_deletes_what_setup_created_in_reverse_order():
    client = set_up()

    report = teardown(client, make_settings(), "dqr")

    assert client.deleted() == FULL_TEARDOWN
    assert [(step.kind, step.name) for step in report] == FULL_TEARDOWN
    assert [step.status for step in report] == ["deleted"] * 5
    force = {key: fields["force"] for _, _, key, fields in client.calls}
    assert force["dqr.sf1"] is True
    assert force["dqr.sf10"] is True
    assert not force["dqr"]
    assert not force["dqr-tpcds"]
    assert not force["dqr-storage"]
    assert client.created() == []
    for api in (
        client.storage_credentials,
        client.external_locations,
        client.catalogs,
        client.schemas,
    ):
        assert api.objects == {}


def test_e5_an_existing_catalog_is_kept():
    client = FakeClient()
    client.catalogs.objects["existing_catalog"] = SimpleNamespace(comment=None)
    settings = make_settings(catalog="existing_catalog")
    setup(client, settings)
    client.calls.clear()

    report = teardown(client, settings, "existing_catalog")

    assert client.deleted() == [
        ("schema", "existing_catalog.sf10"),
        ("schema", "existing_catalog.sf1"),
        ("external location", "dqr-tpcds"),
        ("storage credential", "dqr-storage"),
    ]
    assert summary(report)[2] == ("catalog", "existing_catalog", "kept, not managed")
    assert "existing_catalog" in client.catalogs.objects


@pytest.mark.parametrize(
    ("api", "key", "kind"),
    [
        ("storage_credentials", "dqr-storage", "storage credential"),
        ("external_locations", "dqr-tpcds", "external location"),
        ("schemas", "dqr.sf1", "schema"),
    ],
)
def test_e5_an_object_without_our_marker_is_never_deleted(api, key, kind):
    client = set_up()
    getattr(client, api).objects[key].comment = "someone else's"

    report = teardown(client, make_settings(), "dqr")

    assert (kind, key) not in client.deleted()
    assert len(client.deleted()) == 4
    assert (kind, key, "kept, not managed") in summary(report)


def test_e5_missing_objects_are_reported_absent_without_error():
    client = FakeClient()
    client.storage_credentials.objects["dqr-storage"] = SimpleNamespace(comment=MARKER)

    report = teardown(client, make_settings(), "dqr")

    assert client.deleted() == [("storage credential", "dqr-storage")]
    assert summary(report) == [
        ("schema", "dqr.sf10", "absent"),
        ("schema", "dqr.sf1", "absent"),
        ("catalog", "dqr", "absent"),
        ("external location", "dqr-tpcds", "absent"),
        ("storage credential", "dqr-storage", "deleted"),
    ]


@pytest.mark.parametrize("confirmation", ["", "yes", "DQR", "dqr ", "other_catalog"])
def test_e6_teardown_needs_the_catalog_name_typed_exactly(confirmation):
    client = set_up()

    with pytest.raises(TeardownError):
        teardown(client, make_settings(), confirmation)

    assert client.deleted() == []
    assert len(client.catalogs.objects) == 1
    assert len(client.schemas.objects) == 2
