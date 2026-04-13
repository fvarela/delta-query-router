"""Benchmark execution API — definitions (collection×engine) and runs.

Schema:
  benchmark_definitions: immutable (collection_id, engine_id) pairs
  benchmark_runs: individual executions of a definition
  benchmark_engine_warmups: cold-start probes per run
  benchmark_results: per-query per-engine execution results per run

Benchmark execution is asynchronous: POST /api/benchmarks validates inputs,
creates DB records, and kicks off a background thread. The frontend polls
GET /api/benchmarks/runs/{run_id}/progress for live progress.
"""

import logging
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import db
import engines_api
import query_analyzer

logger = logging.getLogger("routing-service.benchmarks")

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

# Module-level lock to prevent concurrent benchmark executions.
# Only one benchmark batch can run at a time (sequential engine execution).
_benchmark_lock = threading.Lock()

# Module-level set tracking run IDs that have been cancelled.
# Thread-safe via Python's GIL for set.add/discard and `in` checks.
_cancelled_run_ids: set[int] = set()


# --- Pydantic models ---


class CreateBenchmark(BaseModel):
    collection_id: int
    engine_ids: list[str]


# --- Internal helpers ---


def _warmup_duckdb_sync(engine: dict, timeout: float = 30.0) -> float:
    """Send SELECT 1 to a specific DuckDB engine (sync), return elapsed ms."""
    url = engines_api.engine_url(engine)
    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{url}/query", json={"sql": "SELECT 1"})
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


def _execute_query_on_duckdb_sync(
    engine: dict,
    sql: str,
    tables: list[str] | None = None,
    databricks_host: str | None = None,
    databricks_token: str | None = None,
) -> dict:
    """Execute SQL on a specific DuckDB engine (sync). Returns {execution_time_ms, error_message}."""
    url = engines_api.engine_url(engine)
    payload: dict = {"sql": sql}
    if tables and databricks_host and databricks_token:
        payload["tables"] = tables
        payload["databricks_host"] = databricks_host
        payload["databricks_token"] = databricks_token

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{url}/query", json=payload)
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


def _run_benchmark_thread(
    runs: dict,  # engine_id → {definition, run}
    engines: dict,  # engine_id → engine row
    queries: list,  # collection_queries rows
    workspace_client,
    warehouse_id: str | None,
    databricks_host: str | None,
    databricks_token: str | None,
) -> None:
    """Background thread: warm up engines, execute all queries, update DB status.

    Engines are processed sequentially. Each engine goes through:
    1. Warm-up (SELECT 1)
    2. Run all queries
    3. Mark run as complete or failed
    """
    if not _benchmark_lock.acquire(blocking=False):
        # Another benchmark is already running — mark all as failed
        for r in runs.values():
            try:
                db.execute(
                    "UPDATE benchmark_runs SET status = 'failed', error_message = 'Another benchmark is already running', updated_at = NOW() WHERE id = %s",
                    (r["run"]["id"],),
                )
            except Exception:
                pass
        return

    try:
        _run_benchmark_inner(
            runs,
            engines,
            queries,
            workspace_client,
            warehouse_id,
            databricks_host,
            databricks_token,
        )
    finally:
        _benchmark_lock.release()


def _run_benchmark_inner(
    runs: dict,
    engines: dict,
    queries: list,
    workspace_client,
    warehouse_id: str | None,
    databricks_host: str | None,
    databricks_token: str | None,
) -> None:
    """Core benchmark execution (runs inside _benchmark_lock)."""
    total_queries = len(queries)

    for eid, eng in engines.items():
        run_id = runs[eid]["run"]["id"]

        # -- Warm-up phase --
        try:
            db.execute(
                "UPDATE benchmark_runs SET status = 'warming_up', updated_at = NOW() WHERE id = %s",
                (run_id,),
            )

            if eng["engine_type"] == "duckdb":
                cold_start_ms = _warmup_duckdb_sync(eng)
            elif eng["engine_type"] == "databricks_sql":
                if not workspace_client or not warehouse_id:
                    raise RuntimeError("Databricks not configured")
                wh_id = (eng.get("config") or {}).get("warehouse_id", warehouse_id)
                cold_start_ms = _warmup_databricks(workspace_client, wh_id)
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
            db.execute(
                "UPDATE benchmark_runs SET status = 'failed', error_message = %s, updated_at = NOW() WHERE id = %s",
                (f"Warmup failed: {e}", run_id),
            )
            continue  # Skip to next engine instead of aborting all

        # -- Check cancellation before running phase --
        if run_id in _cancelled_run_ids:
            _cancelled_run_ids.discard(run_id)
            db.execute(
                "UPDATE benchmark_runs SET status = 'cancelled', error_message = 'Cancelled before execution', updated_at = NOW() WHERE id = %s",
                (run_id,),
            )
            logger.info(
                "Benchmark run %d for engine %s cancelled before execution", run_id, eid
            )
            continue

        # -- Running phase --
        db.execute(
            "UPDATE benchmark_runs SET status = 'running', updated_at = NOW() WHERE id = %s",
            (run_id,),
        )

        error_count = 0
        cancelled = False
        for query in queries:
            # Check cancellation between queries
            if run_id in _cancelled_run_ids:
                _cancelled_run_ids.discard(run_id)
                cancelled = True
                break

            try:
                if eng["engine_type"] == "duckdb":
                    # Extract table names so DuckDB worker can resolve via credential vending
                    analysis = query_analyzer.analyze_query(query["query_text"])
                    tables = (
                        analysis.tables if analysis and not analysis.error else None
                    )
                    result = _execute_query_on_duckdb_sync(
                        eng,
                        query["query_text"],
                        tables=tables,
                        databricks_host=databricks_host,
                        databricks_token=databricks_token,
                    )
                elif eng["engine_type"] == "databricks_sql":
                    wh_id = (eng.get("config") or {}).get("warehouse_id", warehouse_id)
                    result = _execute_query_on_databricks(
                        workspace_client,
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

            if result.get("error_message"):
                error_count += 1

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

        # -- Complete / Cancelled --
        if cancelled:
            completed = db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM benchmark_results WHERE run_id = %s",
                (run_id,),
            )["cnt"]
            db.execute(
                "UPDATE benchmark_runs SET status = 'cancelled', error_message = %s, updated_at = NOW() WHERE id = %s",
                (f"Cancelled after {completed}/{total_queries} queries", run_id),
            )
            logger.info(
                "Benchmark run %d for engine %s cancelled at %d/%d queries",
                run_id,
                eid,
                completed,
                total_queries,
            )
        else:
            status = "complete" if error_count < total_queries else "failed"
            error_msg = (
                f"{error_count}/{total_queries} queries failed"
                if error_count > 0
                else None
            )
            db.execute(
                "UPDATE benchmark_runs SET status = %s, error_message = %s, updated_at = NOW() WHERE id = %s",
                (status, error_msg, run_id),
            )
            logger.info(
                "Benchmark run %d for engine %s: %s (%d/%d queries ok)",
                run_id,
                eid,
                status,
                total_queries - error_count,
                total_queries,
            )


# --- Endpoints ---


@router.post("", status_code=202)
async def create_benchmark(body: CreateBenchmark):
    """Start a benchmark: validate inputs, create DB records, launch background thread.

    Returns immediately with run_ids and status 'started'. Frontend polls
    GET /api/benchmarks/runs/{run_id}/progress for live updates.
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

    # 3. Check if a benchmark is already running
    if _benchmark_lock.locked():
        raise HTTPException(status_code=409, detail="A benchmark is already running")

    # 4. Create definitions + runs for each engine
    import main as _main

    runs = {}  # engine_id → {definition, run}
    for eid in body.engine_ids:
        definition = _get_or_create_definition(body.collection_id, eid)
        run = db.fetch_one(
            "INSERT INTO benchmark_runs (definition_id, status) VALUES (%s, 'pending') RETURNING *",
            (definition["id"],),
        )
        runs[eid] = {"definition": definition, "run": run}

    # 5. Launch background thread
    thread = threading.Thread(
        target=_run_benchmark_thread,
        args=(
            runs,
            engines,
            queries,
            _main._workspace_client,
            _main._warehouse_id,
            _main._databricks_host,
            _main._databricks_token,
        ),
        daemon=True,
        name="benchmark-runner",
    )
    thread.start()

    run_ids = [r["run"]["id"] for r in runs.values()]
    return {"run_ids": run_ids, "status": "started"}


@router.get("/active")
async def get_active_benchmark():
    """Return active (non-terminal) benchmark runs, if any.

    Used by frontend to detect in-progress benchmarks on page load/reconnect.
    """
    active_runs = db.fetch_all(
        """
        SELECT br.id AS run_id, br.definition_id, br.status, br.created_at, br.updated_at,
               br.error_message,
               bd.collection_id, bd.engine_id,
               c.name AS collection_name,
               e.display_name AS engine_display_name,
               (SELECT COUNT(*) FROM collection_queries cq WHERE cq.collection_id = bd.collection_id) AS total_queries,
               (SELECT COUNT(*) FROM benchmark_results res WHERE res.run_id = br.id) AS completed_queries,
               (SELECT COUNT(*) FROM benchmark_results res WHERE res.run_id = br.id AND res.error_message IS NOT NULL) AS failed_queries
        FROM benchmark_runs br
        JOIN benchmark_definitions bd ON bd.id = br.definition_id
        JOIN collections c ON c.id = bd.collection_id
        LEFT JOIN engines e ON e.id = bd.engine_id
        WHERE br.status IN ('pending', 'warming_up', 'running')
        ORDER BY br.created_at ASC
        """
    )
    return active_runs


@router.get("/runs/{run_id}/progress")
async def get_run_progress(run_id: int):
    """Get live progress for a benchmark run.

    Returns status, query progress counts, engine info, and timing.
    Lightweight query suitable for 2-3s polling.
    """
    run = db.fetch_one(
        """
        SELECT br.id AS run_id, br.definition_id, br.status, br.created_at, br.updated_at,
               br.error_message,
               bd.collection_id, bd.engine_id,
               c.name AS collection_name,
               e.display_name AS engine_display_name
        FROM benchmark_runs br
        JOIN benchmark_definitions bd ON bd.id = br.definition_id
        JOIN collections c ON c.id = bd.collection_id
        LEFT JOIN engines e ON e.id = bd.engine_id
        WHERE br.id = %s
        """,
        (run_id,),
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    total_queries = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM collection_queries WHERE collection_id = %s",
        (run["collection_id"],),
    )["cnt"]

    completed = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM benchmark_results WHERE run_id = %s",
        (run_id,),
    )["cnt"]

    failed = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM benchmark_results WHERE run_id = %s AND error_message IS NOT NULL",
        (run_id,),
    )["cnt"]

    # Calculate elapsed from created_at
    import datetime

    created = run["created_at"]
    if isinstance(created, str):
        created = datetime.datetime.fromisoformat(created)
    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed_ms = (now - created).total_seconds() * 1000

    return {
        "run_id": run["run_id"],
        "definition_id": run["definition_id"],
        "status": run["status"],
        "engine_id": run["engine_id"],
        "engine_display_name": run["engine_display_name"],
        "collection_id": run["collection_id"],
        "collection_name": run["collection_name"],
        "total_queries": total_queries,
        "completed_queries": completed,
        "failed_queries": failed,
        "elapsed_ms": round(elapsed_ms),
        "error_message": run["error_message"],
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int):
    """Cancel a running benchmark run.

    Adds the run_id to the cancellation set, which the background thread
    checks between queries. Already-completed results are preserved.
    """
    run = db.fetch_one(
        "SELECT id, status FROM benchmark_runs WHERE id = %s",
        (run_id,),
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Only cancel runs that are still active
    if run["status"] not in ("pending", "warming_up", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel run with status '{run['status']}'",
        )

    _cancelled_run_ids.add(run_id)
    logger.info("Cancel requested for benchmark run %d", run_id)
    return {"run_id": run_id, "status": "cancel_requested"}


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: int, since: int = 0):
    """Get per-query results for a benchmark run, optionally incremental.

    Query params:
      since: only return results with id > since (for incremental polling)

    Returns a list of result objects with sequence_number, execution_time_ms,
    error_message snippet, and the result row id for use in next `since` call.
    """
    run = db.fetch_one(
        "SELECT id FROM benchmark_runs WHERE id = %s",
        (run_id,),
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    results = db.fetch_all(
        """
        SELECT br.id AS result_id, br.engine_id, br.query_id,
               br.execution_time_ms, br.error_message,
               cq.sequence_number
        FROM benchmark_results br
        LEFT JOIN collection_queries cq ON cq.id = br.query_id
        WHERE br.run_id = %s AND br.id > %s
        ORDER BY br.id ASC
        """,
        (run_id, since),
    )

    return [
        {
            "result_id": r["result_id"],
            "engine_id": r["engine_id"],
            "query_id": r["query_id"],
            "sequence_number": r["sequence_number"],
            "execution_time_ms": r["execution_time_ms"],
            "error_message": (r["error_message"][:120] if r["error_message"] else None),
        }
        for r in results
    ]


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
