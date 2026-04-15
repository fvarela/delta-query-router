"""Ephemeral Databricks warehouse lifecycle management for benchmarks.

Creates temporary serverless SQL warehouses during benchmark execution and
deletes them afterward.  Warehouses are tagged with ``delta-router-managed``
so they can be safely identified for cleanup.

Public API
----------
create_for_benchmark(ws, cluster_size, run_id) -> str
    Create a tagged ephemeral warehouse; return the warehouse ID.
wait_for_running(ws, warehouse_id, timeout_s) -> bool
    Poll until the warehouse reaches RUNNING state.
delete_warehouse(ws, warehouse_id) -> None
    Delete a warehouse **only** if it carries the management tag.
cleanup_orphans(ws) -> int
    Find and delete leftover ephemeral warehouses from crashed runs.
"""

from __future__ import annotations

import logging
import time

from databricks.sdk.service.sql import (
    CreateWarehouseRequestWarehouseType,
    EndpointTagPair,
    EndpointTags,
    State,
)

logger = logging.getLogger("routing-service.ephemeral-warehouses")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NAME_PREFIX = "delta-router-ephemeral-"
_TAG_KEY = "delta-router-managed"
_TAG_VALUE = "true"

# Backoff parameters for wait_for_running
_INITIAL_POLL_INTERVAL_S = 2.0
_MAX_POLL_INTERVAL_S = 30.0
_BACKOFF_MULTIPLIER = 1.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_managed_tag(warehouse) -> bool:
    """Return True if *warehouse* carries the ``delta-router-managed`` tag."""
    tags = getattr(warehouse, "tags", None)
    if tags is None:
        return False
    custom_tags = getattr(tags, "custom_tags", None) or []
    return any(
        getattr(t, "key", None) == _TAG_KEY and getattr(t, "value", None) == _TAG_VALUE
        for t in custom_tags
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_for_benchmark(
    workspace_client,
    cluster_size: str,
    run_id: int,
) -> str:
    """Create a tagged ephemeral serverless warehouse for a benchmark run.

    Parameters
    ----------
    workspace_client:
        Authenticated ``WorkspaceClient`` instance.
    cluster_size:
        Databricks warehouse cluster size (e.g. ``"2X-Small"``, ``"X-Small"``).
    run_id:
        Benchmark run ID — used in the warehouse name for traceability.

    Returns
    -------
    str
        The warehouse ID of the newly created warehouse.
    """
    name = f"{_NAME_PREFIX}{run_id}"
    logger.info(
        "Creating ephemeral warehouse %r (cluster_size=%s) for run %d",
        name,
        cluster_size,
        run_id,
    )

    wait_obj = workspace_client.warehouses.create(
        name=name,
        cluster_size=cluster_size,
        warehouse_type=CreateWarehouseRequestWarehouseType.PRO,
        auto_stop_mins=5,
        enable_serverless_compute=True,
        tags=EndpointTags(
            custom_tags=[EndpointTagPair(key=_TAG_KEY, value=_TAG_VALUE)]
        ),
    )

    warehouse_id: str = wait_obj.response.id
    logger.info("Ephemeral warehouse created: id=%s name=%r", warehouse_id, name)
    return warehouse_id


def wait_for_running(
    workspace_client,
    warehouse_id: str,
    timeout_s: int = 600,
) -> bool:
    """Poll until the warehouse reaches ``RUNNING`` state.

    Uses exponential backoff (2 s → 30 s).  Returns ``False`` if the
    warehouse is deleted or the timeout is exceeded.
    """
    deadline = time.monotonic() + timeout_s
    interval = _INITIAL_POLL_INTERVAL_S

    while time.monotonic() < deadline:
        wh = workspace_client.warehouses.get(warehouse_id)
        state = wh.state

        if state == State.RUNNING:
            logger.info("Warehouse %s is RUNNING", warehouse_id)
            return True

        if state in (State.DELETED, State.DELETING):
            logger.warning(
                "Warehouse %s entered terminal state %s while waiting",
                warehouse_id,
                state,
            )
            return False

        logger.debug(
            "Warehouse %s state=%s, polling again in %.1fs",
            warehouse_id,
            state,
            interval,
        )
        time.sleep(interval)
        interval = min(interval * _BACKOFF_MULTIPLIER, _MAX_POLL_INTERVAL_S)

    logger.warning(
        "Timed out waiting for warehouse %s after %ds", warehouse_id, timeout_s
    )
    return False


def delete_warehouse(workspace_client, warehouse_id: str) -> None:
    """Delete an ephemeral warehouse, with a safety check for the management tag.

    Never raises — logs a warning on any failure.
    """
    try:
        wh = workspace_client.warehouses.get(warehouse_id)
        if not _has_managed_tag(wh):
            logger.warning(
                "Refusing to delete warehouse %s — missing %s tag",
                warehouse_id,
                _TAG_KEY,
            )
            return

        workspace_client.warehouses.delete(warehouse_id)
        logger.info("Deleted ephemeral warehouse %s", warehouse_id)
    except Exception:
        logger.warning(
            "Failed to delete ephemeral warehouse %s", warehouse_id, exc_info=True
        )


def cleanup_orphans(workspace_client) -> int:
    """Delete orphaned ephemeral warehouses left by previous crashed runs.

    Scans all warehouses for names matching ``delta-router-ephemeral-*``
    **and** the ``delta-router-managed`` tag.  Returns the count of
    warehouses deleted.
    """
    deleted = 0
    try:
        for wh in workspace_client.warehouses.list():
            name = getattr(wh, "name", "") or ""
            if not name.startswith(_NAME_PREFIX):
                continue
            if not _has_managed_tag(wh):
                logger.debug(
                    "Skipping warehouse %s (%s) — no management tag",
                    wh.id,
                    name,
                )
                continue

            logger.info("Found orphaned ephemeral warehouse: %s (%s)", wh.id, name)
            delete_warehouse(workspace_client, wh.id)
            deleted += 1
    except Exception:
        logger.warning("Orphan cleanup scan failed", exc_info=True)

    return deleted
