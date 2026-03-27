"""Background query logging — writes to query_logs and routing_decisions."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import db
import json

logger = logging.getLogger("routing-service.query_logger")
_executor = ThreadPoolExecutor(max_workers=2)


def log_query_execution(
    correlation_id: str,
    user_id: str,
    sql: str,
    status: str,
    engine: str,
    reason: str,
    complexity_score: float,
    execution_time_ms: float | None,
    routing_log_events: list[dict] | None = None
) -> None:
    """Insert one row into each of query_logs and routing_decisions.
    Runs inside a single transaction via db.get_conn().
    """
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO query_logs
                           (correlation_id, user_id, query_text, status, completed_at, routing_log_events)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (correlation_id, user_id, sql, status, datetime.now(timezone.utc), json.dumps(routing_log_events) if routing_log_events else None),
                )
                query_log_id = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO routing_decisions
                           (query_log_id, engine, reason, complexity_score)
                       VALUES (%s, %s, %s, %s)""",
                    (query_log_id, engine, reason, complexity_score),
                )
    except Exception:
        logger.exception("Failed to log query execution %s", correlation_id)


def submit_log(**kwargs) -> None:
    """Fire-and-forget: submit log_query_execution to the background executor."""
    _executor.submit(log_query_execution, **kwargs)


def shutdown() -> None:
    """Gracefully shut down the executor. Call from app shutdown."""
    _executor.shutdown(wait=True)
