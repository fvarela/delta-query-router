"""Background log purge — deletes old query_logs and related routing_decisions.

Reads retention settings from the ``log_settings`` table and purges rows from
``query_logs`` (and their child ``routing_decisions``) that are older than
``retention_days``.  Runs on a configurable interval in a daemon thread.

Public API:
    start(interval_seconds=3600)
    stop()
    purge_now() -> int          # manual trigger, returns rows deleted
    get_settings() -> dict
    update_settings(retention_days, max_size_mb) -> dict
"""

from __future__ import annotations

import logging
import threading

import db

logger = logging.getLogger("routing-service.log_cleaner")

_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ── Settings helpers ────────────────────────────────────────────────────────


def get_settings() -> dict:
    """Return current log retention settings."""
    row = db.fetch_one("SELECT * FROM log_settings WHERE id = 1")
    if not row:
        return {"retention_days": 30, "max_size_mb": 1024}
    return {
        "retention_days": row["retention_days"],
        "max_size_mb": row["max_size_mb"],
    }


def update_settings(
    retention_days: int | None = None,
    max_size_mb: int | None = None,
) -> dict:
    """Update log retention settings.  Returns the updated values."""
    fields: dict = {}
    if retention_days is not None:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        fields["retention_days"] = retention_days
    if max_size_mb is not None:
        if max_size_mb < 1:
            raise ValueError("max_size_mb must be >= 1")
        fields["max_size_mb"] = max_size_mb
    if not fields:
        return get_settings()

    set_parts = [f"{k} = %s" for k in fields]
    set_parts.append("updated_at = NOW()")
    values = list(fields.values())
    row = db.fetch_one(
        f"UPDATE log_settings SET {', '.join(set_parts)} WHERE id = 1 RETURNING *",
        tuple(values),
    )
    return {
        "retention_days": row["retention_days"],
        "max_size_mb": row["max_size_mb"],
    }


# ── Purge logic ─────────────────────────────────────────────────────────────


def purge_now() -> int:
    """Delete query_logs older than retention_days.  Returns count deleted."""
    settings = get_settings()
    return _purge_old_logs(settings["retention_days"])


def _purge_old_logs(days: int) -> int:
    """Delete logs older than *days* days.  Returns number of query_logs deleted.

    Deletes child routing_decisions first (FK constraint), then parent
    query_logs.  Uses ``DELETE ... RETURNING id`` to count affected rows.
    """
    # Delete child rows first
    db.execute(
        "DELETE FROM routing_decisions WHERE query_log_id IN "
        "(SELECT id FROM query_logs "
        " WHERE submitted_at < NOW() - make_interval(days => %s))",
        (days,),
    )
    # Delete parent rows — use fetch_all + RETURNING to get a count
    deleted_rows = db.fetch_all(
        "DELETE FROM query_logs "
        "WHERE submitted_at < NOW() - make_interval(days => %s) "
        "RETURNING id",
        (days,),
    )
    deleted = len(deleted_rows) if deleted_rows else 0
    if deleted:
        logger.info("Purged %d query log(s) older than %d days", deleted, days)
    return deleted


# ── Background thread ───────────────────────────────────────────────────────


def start(interval_seconds: int = 3600) -> None:
    """Start the background purge thread (runs every *interval_seconds*)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        logger.warning("Log cleaner already running")
        return

    _stop_event.clear()

    def _loop() -> None:
        logger.info("Log cleaner started (interval=%ds)", interval_seconds)
        try:
            _run_purge()
        except Exception:
            logger.exception("Log cleaner initial run failed")
        while not _stop_event.wait(timeout=interval_seconds):
            try:
                _run_purge()
            except Exception:
                logger.exception("Log cleaner cycle failed")
        logger.info("Log cleaner stopped")

    _thread = threading.Thread(target=_loop, daemon=True, name="log-cleaner")
    _thread.start()


def stop() -> None:
    """Stop the background purge thread."""
    global _thread
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5.0)
        _thread = None


def _run_purge() -> None:
    """Single purge cycle — reads settings and purges."""
    settings = get_settings()
    _purge_old_logs(settings["retention_days"])
