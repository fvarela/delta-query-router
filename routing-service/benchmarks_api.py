"""Benchmark execution API — run collections against engines, store results."""

import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import db
import engines_api

logger = logging.getLogger("routing-service.benchmarks")

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


# --- Pydantic models ---


class CreateBenchmark(BaseModel):
    collection_id: int
    engine_ids: list[str]


# --- Internal helpers ---


async def _warmup_duckdb(engine: dict, timeout: float = 30.0) -> float:
    """Send SELECT 1 to a specific DuckDB engine, return elapsed ms."""
    url = engines_api.engine_url(engine)
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{url}/query", json={"sql": "SELECT 1"})
        resp.raise_for_status()
    return (time.perf_counter() - t0) * 1000


def _warmup_databricks(
    workspace_client, warehouse_id: str, timeout: str = "30s"
) -> float:
    """Send SELECT 1 to a Databricks warehouse, return elapsed ms."""
    from databricks.sdk.service.sql import StatementState

    t0 = time.perf_counter()
    response = workspace_client.statement_execution.execute_statement(
        statement="SELECT 1",
        warehouse_id=warehouse_id,
        wait_timeout=timeout,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    state = response.status.state if response.status else None
    if state != StatementState.SUCCEEDED:
        error_msg = "Warmup failed"
        if response.status and response.status.error:
            error_msg = response.status.error.message or str(response.status.error)
        raise RuntimeError(error_msg)

    return elapsed


async def _execute_query_on_duckdb(
    engine: dict,
    sql: str,
    tables: list[str] | None = None,
    databricks_host: str | None = None,
    databricks_token: str | None = None,
) -> dict:
    """Execute SQL on a specific DuckDB engine. Returns {execution_time_ms, error_message}."""
    url = engines_api.engine_url(engine)
    payload: dict = {"sql": sql}
    if tables and databricks_host and databricks_token:
        payload["tables"] = tables
        payload["databricks_host"] = databricks_host
        payload["databricks_token"] = databricks_token

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{url}/query", json=payload)
        wall_ms = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return {"execution_time_ms": wall_ms, "error_message": str(detail)}

        data = resp.json()
        return {
            "execution_time_ms": data.get("execution_time_ms", wall_ms),
            "error_message": None,
        }
    except Exception as e:
        wall_ms = (time.perf_counter() - t0) * 1000
        return {"execution_time_ms": wall_ms, "error_message": str(e)}


def _execute_query_on_databricks(
    workspace_client,
    warehouse_id: str,
    sql: str,
) -> dict:
    """Execute SQL on Databricks. Returns {execution_time_ms, error_message}."""
    from databricks.sdk.service.sql import StatementState

    t0 = time.perf_counter()
    try:
        response = workspace_client.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=warehouse_id,
            wait_timeout="120s",
        )
        wall_ms = (time.perf_counter() - t0) * 1000

        state = response.status.state if response.status else None
        if state == StatementState.FAILED:
            error_msg = "Unknown error"
            if response.status.error:
                error_msg = response.status.error.message or str(response.status.error)
            return {"execution_time_ms": wall_ms, "error_message": error_msg}
        if state != StatementState.SUCCEEDED:
            return {
                "execution_time_ms": wall_ms,
                "error_message": f"Unexpected state: {state}",
            }

        return {"execution_time_ms": wall_ms, "error_message": None}
    except Exception as e:
        wall_ms = (time.perf_counter() - t0) * 1000
        return {"execution_time_ms": wall_ms, "error_message": str(e)}


# --- Endpoints ---


@router.post("", status_code=201)
async def create_benchmark(body: CreateBenchmark):
    """Run a benchmark: warm up engines, execute all queries, store results."""
    # 1. Validate collection
    collection = db.fetch_one(
        "SELECT * FROM collections WHERE id = %s", (body.collection_id,)
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    queries = db.fetch_all(
        "SELECT * FROM collection_queries WHERE collection_id = %s ORDER BY sequence_number",
        (body.collection_id,),
    )
    if not queries:
        raise HTTPException(status_code=400, detail="Collection has no queries")

    # 2. Validate engines
    if not body.engine_ids:
        raise HTTPException(status_code=400, detail="No engines specified")

    engines = {}
    for eid in body.engine_ids:
        eng = db.fetch_one("SELECT * FROM engines WHERE id = %s", (eid,))
        if not eng:
            raise HTTPException(status_code=404, detail=f"Engine not found: {eid}")
        if not eng["is_active"]:
            raise HTTPException(status_code=400, detail=f"Engine is not active: {eid}")
        engines[eid] = eng

    # 3. Create benchmark row
    benchmark = db.fetch_one(
        "INSERT INTO benchmarks (collection_id, status) VALUES (%s, 'warming_up') RETURNING *",
        (body.collection_id,),
    )
    benchmark_id = benchmark["id"]

    # 4. Warm-up phase
    # Import workspace state from main module for Databricks execution
    import main as _main

    try:
        for eid, eng in engines.items():
            try:
                if eng["engine_type"] == "duckdb":
                    cold_start_ms = await _warmup_duckdb(eng)
                elif eng["engine_type"] == "databricks_sql":
                    if not _main._workspace_client or not _main._warehouse_id:
                        raise RuntimeError("Databricks not configured")
                    wh_id = (eng.get("config") or {}).get(
                        "warehouse_id", _main._warehouse_id
                    )
                    cold_start_ms = _warmup_databricks(_main._workspace_client, wh_id)
                else:
                    raise RuntimeError(f"Unknown engine type: {eng['engine_type']}")

                db.execute(
                    "INSERT INTO benchmark_engine_warmups (benchmark_id, engine_id, cold_start_time_ms) "
                    "VALUES (%s, %s, %s)",
                    (benchmark_id, eid, cold_start_ms),
                )
            except Exception as e:
                logger.warning("Warmup failed for engine %s: %s", eid, e)
                db.execute(
                    "INSERT INTO benchmark_engine_warmups (benchmark_id, engine_id, cold_start_time_ms) "
                    "VALUES (%s, %s, NULL)",
                    (benchmark_id, eid),
                )
                db.execute(
                    "UPDATE benchmarks SET status = 'failed', updated_at = NOW() WHERE id = %s",
                    (benchmark_id,),
                )
                return {
                    "id": benchmark_id,
                    "status": "failed",
                    "error": f"Warmup failed for engine {eid}: {e}",
                }
    except Exception as e:
        db.execute(
            "UPDATE benchmarks SET status = 'failed', updated_at = NOW() WHERE id = %s",
            (benchmark_id,),
        )
        raise HTTPException(status_code=500, detail=f"Warmup phase error: {e}")

    # 5. Running phase
    db.execute(
        "UPDATE benchmarks SET status = 'running', updated_at = NOW() WHERE id = %s",
        (benchmark_id,),
    )

    for query in queries:
        for eid, eng in engines.items():
            try:
                if eng["engine_type"] == "duckdb":
                    result = await _execute_query_on_duckdb(
                        eng,
                        query["query_text"],
                        databricks_host=_main._databricks_host,
                        databricks_token=_main._databricks_token,
                    )
                elif eng["engine_type"] == "databricks_sql":
                    wh_id = (eng.get("config") or {}).get(
                        "warehouse_id", _main._warehouse_id
                    )
                    result = _execute_query_on_databricks(
                        _main._workspace_client,
                        wh_id,
                        query["query_text"],
                    )
                else:
                    result = {
                        "execution_time_ms": None,
                        "error_message": f"Unknown engine type: {eng['engine_type']}",
                    }
            except Exception as e:
                result = {"execution_time_ms": None, "error_message": str(e)}

            db.execute(
                "INSERT INTO benchmark_results (benchmark_id, engine_id, query_id, execution_time_ms, error_message) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    benchmark_id,
                    eid,
                    query["id"],
                    result.get("execution_time_ms"),
                    result.get("error_message"),
                ),
            )

    # 6. Complete
    db.execute(
        "UPDATE benchmarks SET status = 'complete', updated_at = NOW() WHERE id = %s",
        (benchmark_id,),
    )

    return {"id": benchmark_id, "status": "complete"}


@router.get("")
async def list_benchmarks(collection_id: int | None = None):
    """List benchmarks, optionally filtered by collection_id."""
    if collection_id is not None:
        rows = db.fetch_all(
            """
            SELECT b.*, c.name AS collection_name,
                   (SELECT COUNT(DISTINCT br.engine_id) FROM benchmark_results br WHERE br.benchmark_id = b.id) AS engine_count
            FROM benchmarks b
            JOIN collections c ON c.id = b.collection_id
            WHERE b.collection_id = %s
            ORDER BY b.created_at DESC
            """,
            (collection_id,),
        )
    else:
        rows = db.fetch_all(
            """
            SELECT b.*, c.name AS collection_name,
                   (SELECT COUNT(DISTINCT br.engine_id) FROM benchmark_results br WHERE br.benchmark_id = b.id) AS engine_count
            FROM benchmarks b
            JOIN collections c ON c.id = b.collection_id
            ORDER BY b.created_at DESC
            """
        )
    return rows


@router.get("/{benchmark_id}")
async def get_benchmark(benchmark_id: int):
    """Get full benchmark detail: warmups + results with query texts."""
    benchmark = db.fetch_one(
        """
        SELECT b.*, c.name AS collection_name
        FROM benchmarks b
        JOIN collections c ON c.id = b.collection_id
        WHERE b.id = %s
        """,
        (benchmark_id,),
    )
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    warmups = db.fetch_all(
        """
        SELECT bw.*, e.display_name AS engine_display_name
        FROM benchmark_engine_warmups bw
        LEFT JOIN engines e ON e.id = bw.engine_id
        WHERE bw.benchmark_id = %s
        ORDER BY bw.started_at
        """,
        (benchmark_id,),
    )

    results = db.fetch_all(
        """
        SELECT br.*, e.display_name AS engine_display_name,
               cq.query_text, cq.sequence_number
        FROM benchmark_results br
        LEFT JOIN engines e ON e.id = br.engine_id
        LEFT JOIN collection_queries cq ON cq.id = br.query_id
        WHERE br.benchmark_id = %s
        ORDER BY cq.sequence_number, br.engine_id
        """,
        (benchmark_id,),
    )

    return {
        **benchmark,
        "warmups": warmups,
        "results": results,
    }


@router.delete("/{benchmark_id}", status_code=204)
async def delete_benchmark(benchmark_id: int):
    """Delete a benchmark and all its warmups/results (CASCADE)."""
    existing = db.fetch_one("SELECT * FROM benchmarks WHERE id = %s", (benchmark_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    db.execute("DELETE FROM benchmarks WHERE id = %s", (benchmark_id,))
    return Response(status_code=204)
