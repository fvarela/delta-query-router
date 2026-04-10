"""Engine runtime state polling — tracks whether engines are running/stopped.

Maintains an in-memory dict of {engine_id: runtime_state} where runtime_state
is one of: 'running', 'stopped', 'starting', 'unknown'.

Background polling thread checks engine liveness every `interval` seconds.
DuckDB engines are probed via HTTP health endpoint.
Databricks engines are polled via warehouse API.

Public API:
    start_polling(interval_seconds=60)
    stop_polling()
    get_engine_states() -> dict[str, str]
    get_engine_state(engine_id) -> str
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import httpx

import db

logger = logging.getLogger("routing-service.engine_state")

# ── Module-level state ──────────────────────────────────────────────────────
_engine_states: dict[str, str] = {}
_poll_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Injected at startup by main.py — avoids circular import of workspace_client
_get_workspace_client: Callable | None = None


def set_workspace_client_getter(fn: Callable) -> None:
    """Register a callable that returns the current workspace_client (or None)."""
    global _get_workspace_client
    _get_workspace_client = fn


def get_engine_states() -> dict[str, str]:
    """Return a copy of the current engine states."""
    return dict(_engine_states)


def get_engine_state(engine_id: str) -> str:
    """Return the runtime state for a single engine ('unknown' if not tracked)."""
    return _engine_states.get(engine_id, "unknown")


def start_polling(interval_seconds: int = 60) -> None:
    """Start the background polling thread."""
    global _poll_thread
    if _poll_thread is not None and _poll_thread.is_alive():
        logger.warning("Polling already running")
        return

    _stop_event.clear()

    def _loop():
        logger.info("Engine state polling started (interval=%ds)", interval_seconds)
        # Run once immediately, then wait
        _poll_all_engines()
        while not _stop_event.wait(timeout=interval_seconds):
            _poll_all_engines()
        logger.info("Engine state polling stopped")

    _poll_thread = threading.Thread(target=_loop, daemon=True, name="engine-state-poll")
    _poll_thread.start()


def stop_polling() -> None:
    """Stop the background polling thread."""
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=5.0)
        _poll_thread = None


def _poll_all_engines() -> None:
    """Fetch all engines from DB and update their runtime states."""
    try:
        engines = db.fetch_all(
            "SELECT id, engine_type, config, k8s_service_name "
            "FROM engines WHERE is_active = TRUE"
        )
    except Exception:
        logger.exception("Failed to fetch engines for state polling")
        return

    for engine in engines:
        engine_id = engine["id"]
        engine_type = engine["engine_type"]
        try:
            if engine_type == "duckdb":
                _engine_states[engine_id] = _probe_duckdb_health(engine)
            elif engine_type in ("databricks", "databricks_sql"):
                _engine_states[engine_id] = _poll_databricks_warehouse(
                    engine.get("config", {})
                )
            else:
                _engine_states[engine_id] = "unknown"
        except Exception:
            logger.exception("Failed to poll engine %s", engine_id)
            _engine_states[engine_id] = "unknown"


def _probe_duckdb_health(engine: dict) -> str:
    """Probe a DuckDB worker's /health endpoint.

    Returns 'running' if the endpoint responds with 2xx, 'stopped' otherwise.
    Uses a synchronous httpx client with a short timeout.
    """
    svc = engine.get("k8s_service_name")
    if not svc:
        return "unknown"
    url = f"http://{svc}:8002/health"
    try:
        resp = httpx.get(url, timeout=2.0)
        resp.raise_for_status()
        return "running"
    except Exception:
        return "stopped"


def _poll_databricks_warehouse(config: dict) -> str:
    """Poll Databricks warehouse state via SDK.

    Returns 'running', 'stopped', 'starting', or 'unknown'.
    """
    if _get_workspace_client is None:
        return "unknown"

    wc = _get_workspace_client()
    if wc is None:
        return "unknown"

    warehouse_id = config.get("warehouse_id")
    if not warehouse_id:
        return "unknown"

    try:
        warehouse = wc.warehouses.get(warehouse_id)
        state = warehouse.state.value if warehouse.state else None
        # Databricks warehouse states: RUNNING, STOPPED, STARTING, STOPPING, DELETING, DELETED
        state_map = {
            "RUNNING": "running",
            "STOPPED": "stopped",
            "STARTING": "starting",
            "STOPPING": "stopped",
        }
        return state_map.get(state, "unknown")
    except Exception:
        logger.warning("Failed to poll warehouse %s", warehouse_id, exc_info=True)
        return "unknown"
