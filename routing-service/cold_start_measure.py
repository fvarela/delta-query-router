"""Standalone cold start measurement for engines.

Measures the one-time overhead (cold start) of an engine by timing a dummy
query against a stopped warehouse. The query triggers auto-start and the
wall-clock time captures: warehouse startup + session init + catalog warming
+ trivial query execution.

For DuckDB: always 0ms (always-on, no startup cost).
For Databricks: ephemeral warehouse is created, stopped, then a query is
    sent to the stopped warehouse and timed end-to-end.
"""

import logging
import time

import db
import engines_api
import ephemeral_warehouses

logger = logging.getLogger("routing-service.cold_start")


def _get_dummy_table() -> str:
    """Get a table name from the most recent collection for dummy queries.

    Raises ValueError if no collections with tables exist.
    """
    row = db.fetch_one(
        """
        SELECT qf.tables[1] AS table_name
        FROM query_features qf
        JOIN collection_queries cq ON qf.query_id = cq.id
        JOIN collections c ON cq.collection_id = c.id
        WHERE array_length(qf.tables, 1) > 0
        ORDER BY c.created_at DESC
        LIMIT 1
        """
    )
    if not row or not row["table_name"]:
        raise ValueError(
            "No collections with tables available for cold start measurement. "
            "Create a collection with at least one table first."
        )
    return row["table_name"]


def _measure_duckdb(engine: dict, table_name: str, databricks_host: str, databricks_token: str) -> float:
    """Measure cold start for a DuckDB engine.

    For always-on engines: returns 0ms (no startup cost).
    For on-demand engines: scales to 0, then scales to 1, polls health,
    sends a dummy query, and measures wall-clock time from scale-up to
    first successful query response.
    """
    lifecycle = engine.get("lifecycle_mode", "always-on")
    if lifecycle == "always-on":
        logger.info("DuckDB %s cold start: 0ms (always-on)", engine["id"])
        return 0.0

    # On-demand: scale down first, then measure scale-up time
    svc_name = engine.get("k8s_service_name")
    if not svc_name:
        logger.warning("DuckDB %s has no k8s_service_name, returning 0ms", engine["id"])
        return 0.0

    import httpx

    # Scale to 0
    try:
        engines_api._scale_deployment(svc_name, 0)
    except Exception as e:
        logger.warning("Failed to scale down %s for measurement: %s", engine["id"], e)
        return 0.0

    # Wait for pod to terminate (poll health until it fails)
    url = engines_api.engine_url(engine) + "/health"
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(url)
                if r.status_code != 200:
                    break
        except Exception:
            break

    # Now measure: scale to 1 and time until first successful query
    t0 = time.perf_counter()
    try:
        engines_api._scale_deployment(svc_name, 1)
    except Exception as e:
        raise RuntimeError(f"Failed to scale up {engine['id']}: {e}")

    # Poll health until ready (max 120s)
    deadline = time.monotonic() + 120.0
    ready = False
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            with httpx.Client(timeout=2.0) as c:
                r = c.get(url)
                if r.status_code == 200:
                    ready = True
                    break
        except Exception:
            pass

    if not ready:
        raise RuntimeError(f"DuckDB {engine['id']} did not become ready within 120s")

    # Send dummy query to measure full readiness (including DuckDB extensions loading)
    query_url = engines_api.engine_url(engine) + "/query"
    dummy_sql = f"SELECT 1 FROM {table_name} LIMIT 1"
    payload = {"sql": dummy_sql}
    if databricks_host and databricks_token:
        payload["databricks_host"] = databricks_host
        payload["databricks_token"] = databricks_token
        payload["tables"] = [table_name]

    try:
        with httpx.Client(timeout=60.0) as c:
            r = c.post(query_url, json=payload)
            r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"DuckDB {engine['id']} dummy query failed: {e}")

    cold_start_ms = (time.perf_counter() - t0) * 1000
    logger.info("DuckDB %s cold start: %.0fms (on-demand)", engine["id"], cold_start_ms)
    return cold_start_ms


def _measure_databricks(engine: dict, table_name: str, workspace_client) -> float:
    """Measure cold start for a Databricks engine.

    Creates an ephemeral warehouse, waits for it to be RUNNING, stops it,
    waits for STOPPED, then sends a dummy query. The wall-clock time from
    query submission to result captures the full cold start: warehouse
    auto-start + session init + catalog warming + trivial query execution.

    Uses async polling (wait_timeout="0s") to avoid the 50s ceiling on
    synchronous waits — warehouse startup can take 30-120s.
    """
    from databricks.sdk.service.sql import StatementState

    config = engine.get("config") or {}
    cluster_size = config.get("cluster_size", "2X-Small")

    run_id = f"coldstart-{engine['id']}-{int(time.time())}"

    wh_id = ephemeral_warehouses.create_for_benchmark(
        workspace_client, cluster_size, run_id
    )
    try:
        # Wait for initial RUNNING state (so we know it was fully provisioned)
        if not ephemeral_warehouses.wait_for_running(workspace_client, wh_id):
            raise RuntimeError(f"Warehouse {wh_id} failed to reach RUNNING state")

        # Stop the warehouse — this is the state users experience after auto-stop
        workspace_client.warehouses.stop(wh_id)
        logger.info("Waiting for warehouse %s to stop...", wh_id)
        _wait_for_stopped(workspace_client, wh_id)
        logger.info("Warehouse %s is STOPPED, sending cold query...", wh_id)

        # Send query to the STOPPED warehouse and measure wall-clock time.
        # The warehouse will auto-start to serve the query.
        # Use async mode (wait_timeout="0s") then poll — avoids the 50s sync ceiling.
        warmup_sql = f"SELECT 1 FROM {table_name} LIMIT 1"
        t0 = time.perf_counter()

        resp = workspace_client.statement_execution.execute_statement(
            statement=warmup_sql,
            warehouse_id=wh_id,
            wait_timeout="0s",
        )
        statement_id = resp.statement_id
        state = resp.status.state if resp.status else None

        # Poll until terminal state
        timeout_s = 300.0
        poll_interval = 2.0
        deadline = time.monotonic() + timeout_s
        while state in (StatementState.PENDING, StatementState.RUNNING) and time.monotonic() < deadline:
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 10.0)
            resp = workspace_client.statement_execution.get_statement(statement_id)
            state = resp.status.state if resp.status else None

        cold_start_ms = (time.perf_counter() - t0) * 1000

        if state != StatementState.SUCCEEDED:
            err = resp.status.error.message if resp.status and resp.status.error else "unknown"
            raise RuntimeError(f"Cold start query failed (state={state}): {err}")

        logger.info(
            "Databricks %s cold start: %.0fms (query on stopped warehouse)",
            engine["id"], cold_start_ms,
        )
        return cold_start_ms

    finally:
        ephemeral_warehouses.delete_warehouse(workspace_client, wh_id)


def _wait_for_stopped(workspace_client, warehouse_id: str, timeout_s: float = 300.0):
    """Wait for a warehouse to reach STOPPED state."""
    deadline = time.monotonic() + timeout_s
    wait = 2.0
    while time.monotonic() < deadline:
        wh = workspace_client.warehouses.get(warehouse_id)
        state = wh.state.value if wh.state else None
        if state == "STOPPED":
            return
        time.sleep(min(wait, deadline - time.monotonic()))
        wait = min(wait * 1.5, 15.0)
    raise RuntimeError(f"Warehouse {warehouse_id} did not stop within {timeout_s}s")


def measure_cold_start(engine_id: str, workspace_client=None) -> float:
    """Measure cold start for an engine and store in DB.

    Args:
        engine_id: The engine ID to measure.
        workspace_client: Databricks WorkspaceClient (required for Databricks engines).

    Returns:
        The measured cold_start_ms value.

    Raises:
        ValueError: If no collections available or engine not found.
        RuntimeError: If measurement fails.
    """
    # Fetch engine
    engine = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not engine:
        raise ValueError(f"Engine not found: {engine_id}")

    table_name = _get_dummy_table()
    engine_type = engine.get("engine_type", "")

    if engine_type == "duckdb":
        host, token = _get_main_credentials()
        cold_start_ms = _measure_duckdb(engine, table_name, host or "", token or "")
    elif engine_type in ("databricks", "databricks_sql"):
        if not workspace_client:
            workspace_client = _get_workspace_client()
        if not workspace_client:
            raise RuntimeError("Workspace client required for Databricks cold start measurement")
        cold_start_ms = _measure_databricks(engine, table_name, workspace_client)
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")

    # Store measurement
    db.execute(
        "INSERT INTO engine_cold_starts (engine_id, cold_start_ms) VALUES (%s, %s)",
        (engine_id, cold_start_ms),
    )
    logger.info("Stored cold start for %s: %.0fms", engine_id, cold_start_ms)
    return cold_start_ms


def _get_main_credentials() -> tuple[str | None, str | None]:
    """Get Databricks host and token from main module."""
    import main as _main
    return _main._databricks_host, _main._databricks_token


def _get_workspace_client():
    """Get workspace client from main module."""
    import main as _main
    return _main._workspace_client
