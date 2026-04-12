"""Benchmark execution API — definitions (collection×engine) and runs.

Schema:
  benchmark_definitions: immutable (collection_id, engine_id) pairs
  benchmark_runs: individual executions of a definition
  benchmark_engine_warmups: cold-start probes per run
  benchmark_results: per-query per-engine execution results per run
"""

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
            wait_timeout="50s",
        )

        state = response.status.state if response.status else None
        # Poll if still running after initial wait
        while state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(5)
            response = workspace_client.statement_execution.get_statement(
                response.statement_id
            )
            state = response.status.state if response.status else None

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


def _get_or_create_definition(collection_id: int, engine_id: str) -> dict:
    """Get or create a benchmark definition for a (collection, engine) pair."""
    row = db.fetch_one(
        "SELECT * FROM benchmark_definitions WHERE collection_id = %s AND engine_id = %s",
        (collection_id, engine_id),
    )
    if row:
        return row
    return db.fetch_one(
        "INSERT INTO benchmark_definitions (collection_id, engine_id) VALUES (%s, %s) RETURNING *",
        (collection_id, engine_id),
    )


# --- Endpoints ---


@router.post("", status_code=201)
async def create_benchmark(body: CreateBenchmark):
    """Run a benchmark: create definitions + runs, warm up engines, execute queries.

    For each engine_id, a definition (collection×engine) is upserted and a new
    run is created. Engines are warmed up, queries executed, and results stored
    against each run.
    """
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

    # 3. Create definitions + runs for each engine
    import main as _main

    runs = {}  # engine_id → {definition, run}
    for eid in body.engine_ids:
        definition = _get_or_create_definition(body.collection_id, eid)
        run = db.fetch_one(
            "INSERT INTO benchmark_runs (definition_id, status) VALUES (%s, 'warming_up') RETURNING *",
            (definition["id"],),
        )
        runs[eid] = {"definition": definition, "run": run}

    # 4. Warm-up phase
    try:
        for eid, eng in engines.items():
            run_id = runs[eid]["run"]["id"]
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
                    "INSERT INTO benchmark_engine_warmups (run_id, engine_id, cold_start_time_ms) "
                    "VALUES (%s, %s, %s)",
                    (run_id, eid, cold_start_ms),
                )
            except Exception as e:
                logger.warning("Warmup failed for engine %s: %s", eid, e)
                db.execute(
                    "INSERT INTO benchmark_engine_warmups (run_id, engine_id, cold_start_time_ms) "
                    "VALUES (%s, %s, NULL)",
                    (run_id, eid),
                )
                # Mark all runs as failed
                for r in runs.values():
                    db.execute(
                        "UPDATE benchmark_runs SET status = 'failed', updated_at = NOW() WHERE id = %s",
                        (r["run"]["id"],),
                    )
                run_ids = [r["run"]["id"] for r in runs.values()]
                return {
                    "run_ids": run_ids,
                    "status": "failed",
                    "error": f"Warmup failed for engine {eid}: {e}",
                }
    except Exception as e:
        for r in runs.values():
            db.execute(
                "UPDATE benchmark_runs SET status = 'failed', updated_at = NOW() WHERE id = %s",
                (r["run"]["id"],),
            )
        raise HTTPException(status_code=500, detail=f"Warmup phase error: {e}")

    # 5. Running phase — mark all runs as running
    for r in runs.values():
        db.execute(
            "UPDATE benchmark_runs SET status = 'running', updated_at = NOW() WHERE id = %s",
            (r["run"]["id"],),
        )

    for query in queries:
        for eid, eng in engines.items():
            run_id = runs[eid]["run"]["id"]
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
                "INSERT INTO benchmark_results (run_id, engine_id, query_id, execution_time_ms, error_message) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    run_id,
                    eid,
                    query["id"],
                    result.get("execution_time_ms"),
                    result.get("error_message"),
                ),
            )

    # 6. Complete — mark all runs as complete
    for r in runs.values():
        db.execute(
            "UPDATE benchmark_runs SET status = 'complete', updated_at = NOW() WHERE id = %s",
            (r["run"]["id"],),
        )

    run_ids = [r["run"]["id"] for r in runs.values()]
    return {"run_ids": run_ids, "status": "complete"}


@router.get("")
async def list_definitions(
    collection_id: int | None = None,
    engine_id: str | None = None,
):
    """List benchmark definitions, optionally filtered by collection_id and/or engine_id.

    Each definition includes run_count and the latest_run summary.
    """
    where_clauses = []
    params: list = []
    if collection_id is not None:
        where_clauses.append("bd.collection_id = %s")
        params.append(collection_id)
    if engine_id is not None:
        where_clauses.append("bd.engine_id = %s")
        params.append(engine_id)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    rows = db.fetch_all(
        f"""
        SELECT bd.*,
               c.name AS collection_name,
               e.display_name AS engine_display_name,
               (SELECT COUNT(*) FROM benchmark_runs br WHERE br.definition_id = bd.id) AS run_count
        FROM benchmark_definitions bd
        JOIN collections c ON c.id = bd.collection_id
        LEFT JOIN engines e ON e.id = bd.engine_id
        {where_sql}
        ORDER BY bd.created_at DESC
        """,
        tuple(params) if params else None,
    )

    # Attach latest_run for each definition
    result = []
    for row in rows:
        latest_run = db.fetch_one(
            """
            SELECT id, definition_id, status, created_at, updated_at
            FROM benchmark_runs
            WHERE definition_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (row["id"],),
        )
        entry = dict(row)
        entry["latest_run"] = dict(latest_run) if latest_run else None
        result.append(entry)

    return result


@router.get("/{definition_id}")
async def get_definition(definition_id: int):
    """Get a benchmark definition with all its runs."""
    definition = db.fetch_one(
        """
        SELECT bd.*,
               c.name AS collection_name,
               e.display_name AS engine_display_name
        FROM benchmark_definitions bd
        JOIN collections c ON c.id = bd.collection_id
        LEFT JOIN engines e ON e.id = bd.engine_id
        WHERE bd.id = %s
        """,
        (definition_id,),
    )
    if not definition:
        raise HTTPException(status_code=404, detail="Benchmark definition not found")

    runs = db.fetch_all(
        """
        SELECT id, definition_id, status, created_at, updated_at
        FROM benchmark_runs
        WHERE definition_id = %s
        ORDER BY created_at DESC
        """,
        (definition_id,),
    )

    return {
        **definition,
        "run_count": len(runs),
        "runs": runs,
    }


@router.get("/{definition_id}/runs")
async def list_runs(definition_id: int):
    """List runs for a benchmark definition, ordered by created_at desc."""
    definition = db.fetch_one(
        "SELECT * FROM benchmark_definitions WHERE id = %s",
        (definition_id,),
    )
    if not definition:
        raise HTTPException(status_code=404, detail="Benchmark definition not found")

    runs = db.fetch_all(
        """
        SELECT id, definition_id, status, created_at, updated_at
        FROM benchmark_runs
        WHERE definition_id = %s
        ORDER BY created_at DESC
        """,
        (definition_id,),
    )
    return runs


@router.get("/{definition_id}/runs/{run_id}")
async def get_run(definition_id: int, run_id: int):
    """Get run details with warmup results and query results."""
    run = db.fetch_one(
        """
        SELECT * FROM benchmark_runs
        WHERE id = %s AND definition_id = %s
        """,
        (run_id, definition_id),
    )
    if not run:
        raise HTTPException(status_code=404, detail="Benchmark run not found")

    warmups = db.fetch_all(
        """
        SELECT bw.*, e.display_name AS engine_display_name
        FROM benchmark_engine_warmups bw
        LEFT JOIN engines e ON e.id = bw.engine_id
        WHERE bw.run_id = %s
        ORDER BY bw.started_at
        """,
        (run_id,),
    )

    results = db.fetch_all(
        """
        SELECT br.*, e.display_name AS engine_display_name,
               cq.query_text, cq.sequence_number
        FROM benchmark_results br
        LEFT JOIN engines e ON e.id = br.engine_id
        LEFT JOIN collection_queries cq ON cq.id = br.query_id
        WHERE br.run_id = %s
        ORDER BY cq.sequence_number, br.engine_id
        """,
        (run_id,),
    )

    return {
        **run,
        "warmups": warmups,
        "results": results,
    }


@router.delete("/{definition_id}", status_code=204)
async def delete_definition(definition_id: int):
    """Delete a benchmark definition and all its runs/warmups/results (CASCADE)."""
    existing = db.fetch_one(
        "SELECT * FROM benchmark_definitions WHERE id = %s", (definition_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Benchmark definition not found")
    db.execute("DELETE FROM benchmark_definitions WHERE id = %s", (definition_id,))
    return Response(status_code=204)


@router.delete("/{definition_id}/runs/{run_id}", status_code=204)
async def delete_run(definition_id: int, run_id: int):
    """Delete a specific benchmark run and its warmups/results (CASCADE)."""
    existing = db.fetch_one(
        "SELECT * FROM benchmark_runs WHERE id = %s AND definition_id = %s",
        (run_id, definition_id),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    db.execute("DELETE FROM benchmark_runs WHERE id = %s", (run_id,))
    return Response(status_code=204)
