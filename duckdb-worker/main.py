"""DuckDB worker — executes SQL queries, optionally reading Unity Catalog
Delta tables via credential vending.

For UC table queries, the flow is:
  1. credential_vending resolves table names to signed parquet file URLs
  2. SQL is rewritten to replace three-part names with read_parquet() calls
  3. DuckDB executes the rewritten SQL via httpfs (no Azure SDK needed)
"""

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager

import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from credential_vending import CredentialVendingError, ResolvedTable, resolve_tables

logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    sql: str
    # Optional: for queries that reference Unity Catalog tables
    tables: list[str] | None = None
    databricks_host: str | None = None
    databricks_token: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install httpfs once at startup (cached on disk for subsequent connections)
    init_db = duckdb.connect(":memory:")
    init_db.install_extension("httpfs")
    init_db.close()
    yield


app = FastAPI(lifespan=lifespan)


def _create_connection() -> duckdb.DuckDBPyConnection:
    """Create a fresh DuckDB connection with httpfs loaded.

    Each query gets its own connection to avoid thread-safety issues.
    DuckDB in-memory connections are cheap to create (~1ms), and this
    ensures no cross-thread sharing of the connection object when
    running queries via asyncio.to_thread().
    """
    conn = duckdb.connect(":memory:")
    conn.load_extension("httpfs")
    return conn


def _build_read_parquet_expr(file_urls: list[str]) -> str:
    """Build a DuckDB read_parquet() expression for one or more signed URLs.

    For a single file:  read_parquet('https://...?sas=...', union_by_name=true)
    For multiple files:  read_parquet(['https://...', '...'], union_by_name=true)

    union_by_name=true handles schema mismatches across parquet files (e.g.
    some files have Databricks internal _row-id-col-* deletion vector columns
    that others don't).
    """
    if len(file_urls) == 1:
        escaped = file_urls[0].replace("'", "''")
        return f"read_parquet('{escaped}', union_by_name=true)"
    else:
        escaped_list = ", ".join(
            f"'{u.replace(chr(39), chr(39) + chr(39))}'" for u in file_urls
        )
        return f"read_parquet([{escaped_list}], union_by_name=true)"


def _rewrite_sql(sql: str, resolved: dict[str, ResolvedTable]) -> str:
    """Replace three-part table references in SQL with read_parquet() calls.

    Handles both quoted and unquoted identifiers. Replaces longest names
    first to avoid partial matches.
    """
    rewritten = sql

    # Sort by name length descending to avoid partial replacements
    for full_name in sorted(resolved, key=len, reverse=True):
        table = resolved[full_name]
        parquet_expr = _build_read_parquet_expr(table.file_urls)

        # Build regex pattern matching the three-part name with optional quoting
        parts = full_name.split(".")
        part_patterns = []
        for part in parts:
            escaped = re.escape(part)
            # Match: part OR `part` OR "part" (case-insensitive)
            part_patterns.append(rf"(?:`{escaped}`|\"{escaped}\"|{escaped})")
        pattern = r"\.".join(part_patterns)
        rewritten = re.sub(pattern, parquet_expr, rewritten, flags=re.IGNORECASE)

    return rewritten


@app.get("/health")
async def health():
    return {"status": "ok", "engine": "duckdb"}


@app.post("/query")
async def query(request: QueryRequest):
    start = time.perf_counter()

    # If tables + credentials are provided, resolve them via credential vending
    resolved: dict[str, ResolvedTable] = {}
    if request.tables and request.databricks_host and request.databricks_token:
        try:
            # Run in a thread to avoid blocking the async event loop
            # (credential vending makes synchronous HTTP calls and reads
            # Delta logs from Azure, which can take 10-30+ seconds)
            resolved = await asyncio.to_thread(
                resolve_tables,
                request.databricks_host,
                request.databricks_token,
                request.tables,
            )
        except CredentialVendingError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Credential vending failed: {e}",
            )

    # Rewrite SQL to replace table references with read_parquet()
    sql = request.sql
    if resolved:
        sql = _rewrite_sql(sql, resolved)
        logger.info("Rewritten SQL: %s", sql[:500])

    try:
        # DuckDB execute is synchronous — run in a thread with a fresh
        # per-query connection to avoid thread-safety issues
        def _execute():
            conn = _create_connection()
            try:
                logger.info("Executing SQL (%d chars)...", len(sql))
                result = conn.execute(sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
                logger.info(
                    "Query returned %d rows, %d columns", len(rows), len(columns)
                )
                return columns, rows
            finally:
                conn.close()

        columns, rows = await asyncio.to_thread(_execute)
        execution_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": execution_time_ms,
        }
    except duckdb.Error as e:
        raise HTTPException(status_code=400, detail=str(e))
