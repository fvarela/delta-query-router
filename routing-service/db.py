"""PostgreSQL connection pool and query helpers for routing-service."""

import os
import logging
from contextlib import contextmanager
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("routing-service.db")
# Build DATABASE_URL from individual env vars (matching K8s manifest)
_DATABASE_URL = "postgresql://{user}:{password}@{host}:{port}/{db}".format(
    user=os.environ.get("POSTGRES_USER", "delta"),
    password=os.environ.get("POSTGRES_PASSWORD", ""),
    host=os.environ.get("POSTGRES_HOST", "localhost"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    db=os.environ.get("POSTGRES_DB", "deltarouter"),
)
_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))
_pool: ThreadedConnectionPool | None = None


def init_db():
    """Initialize the connection pool. Call once at startup."""
    global _pool
    try:
        _pool = ThreadedConnectionPool(_POOL_MIN, _POOL_MAX, _DATABASE_URL)
        # Verify connectivity
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        logger.info(
            "PostgreSQL connection pool initialized (min=%d, max=%d)",
            _POOL_MIN,
            _POOL_MAX,
        )
    except Exception:
        logger.exception("Failed to initialize PostgreSQL connection pool")
        raise


def close_db():
    """Close all pool connections. Call on shutdown."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


@contextmanager
def get_conn():
    """Check out a connection from the pool. Auto-returns on exit."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized — call init_db() first")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def execute(sql: str, params: tuple | None = None) -> None:
    """Execute INSERT/UPDATE/DELETE. No return value."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def fetch_one(sql: str, params: tuple | None = None) -> dict | None:
    """Execute a query and return the first row as a dict, or None."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_all(sql: str, params: tuple | None = None) -> list[dict]:
    """Execute a query and return all rows as a list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
