"""Idle timer for on-demand DuckDB engines.

Tracks last query time per engine. A background thread periodically checks
on-demand engines and scales them down after their idle timeout expires.
"""

import logging
import threading
import time as _time
from datetime import datetime, timezone

import db
import engines_api

logger = logging.getLogger("routing-service.idle_timer")

# In-memory tracking of last query time per engine_id
_last_query_time: dict[str, float] = {}
_lock = threading.Lock()
_timer_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Check interval (seconds)
_CHECK_INTERVAL = 30


def record_query(engine_id: str) -> None:
    """Record that a query was just sent to an engine."""
    with _lock:
        _last_query_time[engine_id] = _time.time()


def _check_idle_engines() -> None:
    """Check all on-demand DuckDB engines and scale down idle ones."""
    try:
        engines = db.fetch_all(
            "SELECT id, k8s_service_name, idle_timeout_minutes "
            "FROM engines WHERE engine_type = 'duckdb' AND lifecycle_mode = 'on-demand' AND is_active = TRUE"
        )
    except Exception as e:
        logger.warning("Failed to fetch engines for idle check: %s", e)
        return

    now = _time.time()
    with _lock:
        for eng in engines:
            eid = eng["id"]
            last = _last_query_time.get(eid)
            if last is None:
                # Never queried — not running or just started, skip
                continue
            idle_seconds = now - last
            timeout_seconds = eng["idle_timeout_minutes"] * 60
            if idle_seconds > timeout_seconds:
                svc = eng.get("k8s_service_name")
                if svc:
                    logger.info(
                        "Engine %s idle for %.0fs (timeout %ds) — scaling down",
                        eid, idle_seconds, timeout_seconds,
                    )
                    try:
                        engines_api._scale_deployment(svc, 0)
                        # Remove from tracking
                        _last_query_time.pop(eid, None)
                    except Exception as e:
                        logger.warning("Failed to scale down %s: %s", eid, e)


def _timer_loop() -> None:
    """Background loop that checks idle engines periodically."""
    while not _stop_event.is_set():
        _stop_event.wait(_CHECK_INTERVAL)
        if _stop_event.is_set():
            break
        _check_idle_engines()


def start() -> None:
    """Start the idle timer background thread."""
    global _timer_thread
    if _timer_thread is not None and _timer_thread.is_alive():
        return
    _stop_event.clear()
    _timer_thread = threading.Thread(target=_timer_loop, daemon=True, name="idle-timer")
    _timer_thread.start()
    logger.info("Idle timer started (check interval: %ds)", _CHECK_INTERVAL)


def stop() -> None:
    """Stop the idle timer background thread."""
    _stop_event.set()
    if _timer_thread is not None:
        _timer_thread.join(timeout=5)
    logger.info("Idle timer stopped")
