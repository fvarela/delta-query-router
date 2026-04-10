import os
import time
import uuid

import httpx
import psycopg2
import db
import catalog_service
import query_analyzer
import routing_engine
import permissions
import query_logger
import auth
import collections_api
import engines_api
import benchmarks_api
import probes_api
import models_api
import permissions_api
import tpcds_api
import routing_profiles_api
from auth import verify_token
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import (
    DatabricksError,
    Unauthenticated,
    PermissionDenied,
    NotFound,
    BadRequest,
    InvalidState,
    TooManyRequests,
    TemporarilyUnavailable,
    DeadlineExceeded,
    InternalError,
    OperationFailed,
    OperationTimeout,
)
import requests as _requests  # for catching SDK network errors

app = FastAPI()
app.include_router(auth.router)
app.include_router(collections_api.router, dependencies=[Depends(verify_token)])
app.include_router(engines_api.router, dependencies=[Depends(verify_token)])
app.include_router(benchmarks_api.router, dependencies=[Depends(verify_token)])
app.include_router(probes_api.router, dependencies=[Depends(verify_token)])
app.include_router(models_api.router, dependencies=[Depends(verify_token)])
app.include_router(permissions_api.router, dependencies=[Depends(verify_token)])
app.include_router(tpcds_api.router, dependencies=[Depends(verify_token)])
app.include_router(routing_profiles_api.router, dependencies=[Depends(verify_token)])


def _databricks_error_to_http(e: Exception) -> HTTPException:
    """Translate Databricks SDK and network exceptions into user-friendly HTTPExceptions.

    Order matters: subclasses must be checked before their parents
    (e.g. InvalidState before BadRequest, ResourceDoesNotExist before NotFound).
    """
    # --- Auth errors ---
    if isinstance(e, Unauthenticated):
        return HTTPException(
            status_code=401, detail="Invalid or expired Databricks token."
        )
    if isinstance(e, PermissionDenied):
        return HTTPException(
            status_code=403, detail=f"Insufficient Databricks permissions: {e}"
        )
    # --- Client errors ---
    if isinstance(e, NotFound):
        return HTTPException(
            status_code=404, detail=f"Databricks resource not found: {e}"
        )
    if isinstance(e, InvalidState):
        return HTTPException(
            status_code=409, detail=f"Databricks resource in invalid state: {e}"
        )
    if isinstance(e, TooManyRequests):
        return HTTPException(
            status_code=429, detail="Databricks rate limit exceeded. Retry in a moment."
        )
    if isinstance(e, BadRequest):
        return HTTPException(status_code=400, detail=f"Databricks request error: {e}")
    # --- Server / transient errors ---
    if isinstance(e, TemporarilyUnavailable):
        return HTTPException(
            status_code=503, detail="Databricks service temporarily unavailable."
        )
    if isinstance(e, DeadlineExceeded):
        return HTTPException(status_code=504, detail="Databricks request timed out.")
    if isinstance(e, InternalError):
        return HTTPException(status_code=502, detail=f"Databricks internal error: {e}")
    # --- Catch-all DatabricksError ---
    if isinstance(e, DatabricksError):
        return HTTPException(status_code=502, detail=f"Databricks error: {e}")
    # --- SDK operation errors (not DatabricksError subclasses) ---
    if isinstance(e, OperationTimeout):
        return HTTPException(status_code=504, detail="Databricks operation timed out.")
    if isinstance(e, OperationFailed):
        return HTTPException(
            status_code=502, detail=f"Databricks operation failed: {e}"
        )
    # --- Network errors (survive SDK retry logic) ---
    if isinstance(e, _requests.ConnectionError):
        return HTTPException(
            status_code=502,
            detail="Cannot reach Databricks. Check the workspace URL and network connectivity.",
        )
    if isinstance(e, _requests.Timeout):
        return HTTPException(
            status_code=504, detail="Connection to Databricks timed out."
        )
    # --- Unknown ---
    return HTTPException(
        status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}"
    )


# Backend connection config from environment
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "deltarouter")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "delta")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

_workspace_client: WorkspaceClient | None = None
_databricks_host: str | None = None
_databricks_token: str | None = None
_databricks_username: str | None = None
_warehouse_id: str | None = None

import logging

logger = logging.getLogger("routing-service")


@app.on_event("startup")
async def load_databricks_credentials():
    global \
        _workspace_client, \
        _databricks_host, \
        _databricks_token, \
        _databricks_username, \
        _warehouse_id
    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")
    if not host or not token:
        logger.info(
            "No DATABRICKS_HOST/DATABRICKS_TOKEN in environment, skipping auto-connect"
        )
        return
    try:
        wc = WorkspaceClient(host=host, token=token)
        me = wc.current_user.me()
        _workspace_client = wc
        _databricks_host = host
        _databricks_token = token
        _databricks_username = me.user_name
        _warehouse_id = os.environ.get("SQL_WAREHOUSE_ID")
        logger.info(f"Databricks credentials loaded from environment: {me.user_name}")
    except Exception as e:
        logger.warning(f"Failed to load Databricks credentials from environment: {e}")


@app.on_event("startup")
async def init_database():
    db.init_db()


@app.on_event("shutdown")
async def close_database():
    query_logger.shutdown()
    db.close_db()


class DatabricksCredentials(BaseModel):
    host: str
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


def _get_k8s_core_api():
    """Return a K8s CoreV1Api client, or None if not running in-cluster."""
    from kubernetes import client as k8s_client, config as k8s_config

    try:
        k8s_config.load_incluster_config()
    except Exception:
        return None
    return k8s_client.CoreV1Api()


def _save_to_k8s_secret(creds: DatabricksCredentials):
    from kubernetes import client as k8s_client

    v1 = _get_k8s_core_api()
    if v1 is None:
        return  # Not running in cluster, skip silently
    secret_data = {"DATABRICKS_HOST": creds.host}
    if creds.token:
        secret_data["DATABRICKS_TOKEN"] = creds.token
    if creds.client_id:
        secret_data["DATABRICKS_CLIENT_ID"] = creds.client_id
    if creds.client_secret:
        secret_data["DATABRICKS_CLIENT_SECRET"] = creds.client_secret
    # Preserve warehouse_id so replace doesn't wipe it
    if _warehouse_id:
        secret_data["SQL_WAREHOUSE_ID"] = _warehouse_id
    secret = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(name="databricks-credentials"),
        string_data=secret_data,
    )
    try:
        v1.read_namespaced_secret("databricks-credentials", "default")
        v1.replace_namespaced_secret("databricks-credentials", "default", secret)
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            v1.create_namespaced_secret("default", secret)
        else:
            raise


def _patch_k8s_secret(key: str, value: str):
    """Patch a single key into the databricks-credentials K8s Secret."""
    import base64
    from kubernetes import client as k8s_client

    v1 = _get_k8s_core_api()
    if v1 is None:
        return  # Not running in cluster, skip silently
    encoded = base64.b64encode(value.encode()).decode()
    body = {"data": {key: encoded}}
    try:
        v1.patch_namespaced_secret("databricks-credentials", "default", body)
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            # Secret doesn't exist yet — create it with just this key
            secret = k8s_client.V1Secret(
                metadata=k8s_client.V1ObjectMeta(name="databricks-credentials"),
                string_data={key: value},
            )
            v1.create_namespaced_secret("default", secret)
        else:
            raise


@app.post("/api/settings/databricks")
async def save_databricks_settings(
    creds: DatabricksCredentials, user: auth.UserContext = Depends(verify_token)
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    global _workspace_client, _databricks_host, _databricks_token, _databricks_username
    try:
        if creds.token:
            wc = WorkspaceClient(host=creds.host, token=creds.token)
        elif creds.client_id and creds.client_secret:
            wc = WorkspaceClient(
                host=creds.host,
                client_id=creds.client_id,
                client_secret=creds.client_secret,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide either token or client_id+client_secret",
            )
        me = wc.current_user.me()
    except HTTPException:
        raise
    except Exception as e:
        raise _databricks_error_to_http(e)
    _workspace_client = wc
    _databricks_host = creds.host
    _databricks_token = creds.token  # may be None for client_id/secret auth
    _databricks_username = me.user_name
    _save_to_k8s_secret(creds)
    return {"status": "connected", "host": creds.host, "username": me.user_name}


@app.get("/api/settings/databricks")
async def get_databricks_settings(user: auth.UserContext = Depends(verify_token)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if _workspace_client is None:
        return {"configured": False}
    return {
        "configured": True,
        "host": _databricks_host,
        "username": _databricks_username,
        "warehouse_id": _warehouse_id,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/backends")
async def health_backends():
    backends = {}
    # Check PostgreSQL
    try:
        db.fetch_one("SELECT 1")
        backends["postgresql"] = {"status": "connected"}
    except Exception as e:
        backends["postgresql"] = {"status": "error", "detail": str(e)}

    # Check DuckDB Workers (all active engines from DB)
    async with httpx.AsyncClient(timeout=3.0) as client:
        for eng in engines_api.get_duckdb_engines():
            svc = eng.get("k8s_service_name", eng["id"])
            url = f"http://{svc}:8002"
            try:
                resp = await client.get(f"{url}/health")
                resp.raise_for_status()
                backends[svc] = {"status": "connected"}
            except Exception as e:
                backends[svc] = {"status": "error", "detail": str(e)}
    if _workspace_client is None:
        backends["databricks"] = {"status": "not_configured"}
    else:
        try:
            _workspace_client.current_user.me()
            backends["databricks"] = {"status": "connected"}
        except Exception as e:
            backends["databricks"] = {"status": "error", "detail": str(e)}
    return backends


# Predefined cluster-size → engine-ID mapping for serverless warehouses
_CLUSTER_SIZE_TO_ENGINE: dict[str, str] = {
    "2X-Small": "databricks-serverless-2xs",
    "X-Small": "databricks-serverless-xs",
    "Small": "databricks-serverless-s",
}


def _match_warehouse_to_engine(wh) -> str | None:
    """Match a Databricks warehouse to a predefined engine ID.

    Only matches serverless warehouses with known cluster sizes.
    Returns None for non-serverless or unrecognized sizes.
    """
    wh_type = wh.warehouse_type.value if wh.warehouse_type else None
    if wh_type != "PRO":
        return None
    size = wh.cluster_size if wh.cluster_size else None
    return _CLUSTER_SIZE_TO_ENGINE.get(size)


@app.get("/api/databricks/warehouses")
async def list_warehouses(user: auth.UserContext = Depends(verify_token)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if _workspace_client is None:
        raise HTTPException(status_code=400, detail="Databricks not configured")
    try:
        warehouses = _workspace_client.warehouses.list()
        return [
            {
                "id": wh.id,
                "name": wh.name,
                "state": wh.state.value if wh.state else "UNKNOWN",
                "cluster_size": wh.cluster_size if wh.cluster_size else None,
                "warehouse_type": wh.warehouse_type.value
                if wh.warehouse_type
                else None,
                "matched_engine_id": _match_warehouse_to_engine(wh),
            }
            for wh in warehouses
        ]
    except Exception as e:
        raise _databricks_error_to_http(e)


class WarehouseSelection(BaseModel):
    warehouse_id: str


class QueryExecutionRequest(BaseModel):
    sql: str
    routing_mode: str = "smart"  # "smart", "duckdb", or "databricks"


@app.put("/api/settings/warehouse")
async def save_warehouse(
    body: WarehouseSelection, user: auth.UserContext = Depends(verify_token)
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    global _warehouse_id
    _warehouse_id = body.warehouse_id
    try:
        _patch_k8s_secret("SQL_WAREHOUSE_ID", body.warehouse_id)
        logger.info(f"Warehouse ID persisted to K8s Secret: {body.warehouse_id}")
    except Exception as e:
        logger.warning(f"Failed to persist warehouse ID to K8s Secret: {e}")
    return {"warehouse_id": body.warehouse_id, "status": "saved"}


@app.get("/api/databricks/catalogs")
async def list_catalogs(user: auth.UserContext = Depends(verify_token)):
    if _workspace_client is None:
        raise HTTPException(status_code=400, detail="No Databricks workspace connected")
    try:
        catalogs = _workspace_client.catalogs.list()
        return [{"name": c.name} for c in catalogs]
    except Exception as e:
        raise _databricks_error_to_http(e)


@app.get("/api/databricks/catalogs/{catalog}/schemas")
async def list_schemas(catalog: str, user: auth.UserContext = Depends(verify_token)):
    if _workspace_client is None:
        raise HTTPException(status_code=400, detail="No Databricks workspace connected")
    try:
        schemas = list(_workspace_client.schemas.list(catalog_name=catalog))
    except Exception as e:
        raise _databricks_error_to_http(e)

    # Check EXTERNAL_USE_SCHEMA grant for each schema
    # NOTE: SDK grants.get(securable_type=SecurableType.SCHEMA) sends uppercase
    # "SCHEMA" in the URL path, but the API requires lowercase "schema".
    # Use raw api_client.do() as a workaround.
    result = []
    for s in schemas:
        external_use_schema = False
        full_name = f"{s.catalog_name}.{s.name}"
        try:
            resp = _workspace_client.api_client.do(
                "GET",
                f"/api/2.1/unity-catalog/permissions/schema/{full_name}",
            )
            for assignment in resp.get("privilege_assignments", []):
                if "EXTERNAL_USE_SCHEMA" in (assignment.get("privileges") or []):
                    external_use_schema = True
                    break
        except Exception as e:
            logger.debug("Could not check grants for schema %s: %s", full_name, e)
        result.append(
            {
                "name": s.name,
                "catalog_name": s.catalog_name,
                "external_use_schema": external_use_schema,
            }
        )
    return result


@app.get("/api/databricks/catalogs/{catalog}/schemas/{schema}/tables")
async def list_tables(
    catalog: str, schema: str, user: auth.UserContext = Depends(verify_token)
):
    if _workspace_client is None:
        raise HTTPException(status_code=400, detail="No Databricks workspace connected")
    try:
        tables = _workspace_client.tables.list(
            catalog_name=catalog, schema_name=schema, include_manifest_capabilities=True
        )
        result = []
        cache_entries = []
        for t in tables:
            table_type = t.table_type.value if t.table_type else "UNKNOWN"
            data_source_format = (
                t.data_source_format.value if t.data_source_format else None
            )
            size_bytes = None
            row_count = None
            if t.properties:
                size_str = t.properties.get("spark.sql.statistics.totalSize")
                if size_str is not None:
                    try:
                        size_bytes = int(size_str)
                    except ValueError:
                        pass
                rows_str = t.properties.get("spark.sql.statistics.numRows")
                if rows_str is not None:
                    try:
                        row_count = int(rows_str)
                    except ValueError:
                        pass
            has_rls = t.row_filter is not None
            has_column_masking = any(col.mask is not None for col in (t.columns or []))
            capabilities = []
            if t.securable_kind_manifest and t.securable_kind_manifest.capabilities:
                capabilities = t.securable_kind_manifest.capabilities
            external_engine_read_support = (
                "HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT" in capabilities
            )
            columns = [
                {
                    "name": col.name,
                    "type_text": col.type_text or col.type_name.value
                    if col.type_name
                    else "UNKNOWN",
                }
                for col in (t.columns or [])
            ]
            result.append(
                {
                    "name": t.name,
                    "full_name": t.full_name,
                    "table_type": table_type,
                    "data_source_format": data_source_format,
                    "size_bytes": size_bytes,
                    "row_count": row_count,
                    "storage_location": t.storage_location,
                    "external_engine_read_support": external_engine_read_support,
                    "columns": columns,
                }
            )

            # Build cache entry for warm-on-browse
            cache_entries.append(
                catalog_service.TableMetadata(
                    full_name=t.full_name,
                    table_type=table_type,
                    data_source_format=data_source_format or "UNKNOWN",
                    storage_location=t.storage_location,
                    size_bytes=size_bytes,
                    has_rls=has_rls,
                    has_column_masking=has_column_masking,
                    external_engine_read_support=external_engine_read_support,
                    cached=False,
                )
            )
        # Warm the metadata cache (best-effort, never breaks browse response)
        for entry in cache_entries:
            try:
                catalog_service._write_to_cache(entry)
            except Exception:
                logger.warning(
                    "Failed to cache metadata for %s", entry.full_name, exc_info=True
                )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise _databricks_error_to_http(e)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

MAX_RESULT_ROWS = 1000


async def _execute_on_duckdb(sql: str, tables: list[str] | None = None) -> dict:
    """Execute SQL on the first running DuckDB worker via HTTP.

    Probes all active DuckDB engines (from DB, ordered by cost_tier) and uses
    the first that responds to a health check.  If tables are provided and
    Databricks credentials are available, passes them to the worker for
    credential vending.
    """
    # Find the first running DuckDB worker
    worker_url: str | None = None
    async with httpx.AsyncClient(timeout=3.0) as probe_client:
        for eng in engines_api.get_duckdb_engines():
            url = engines_api.engine_url(eng)
            try:
                resp = await probe_client.get(f"{url}/health")
                resp.raise_for_status()
                worker_url = url
                break
            except Exception:
                continue

    if worker_url is None:
        raise HTTPException(
            status_code=503,
            detail="No DuckDB worker is currently running. Start one from the Engines panel.",
        )

    payload: dict = {"sql": sql}

    # Pass Databricks credentials + table names for credential vending
    if tables and _databricks_host and _databricks_token:
        payload["tables"] = tables
        payload["databricks_host"] = _databricks_host
        payload["databricks_token"] = _databricks_token

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{worker_url}/query", json=payload)
        if resp.status_code != 200:
            detail = (
                resp.json().get("detail", resp.text)
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text
            )
            # Enhance cryptic DuckDB errors with actionable guidance
            if "does not exist" in detail and "Catalog" in detail:
                detail = (
                    f"{detail} — Credential vending may have failed to load "
                    "the table. Check DuckDB worker logs for details."
                )
            raise HTTPException(
                status_code=502, detail=f"DuckDB worker error: {detail}"
            )
        data = resp.json()
        return {
            "columns": data["columns"],
            "rows": data["rows"][:MAX_RESULT_ROWS],
            "row_count": data["row_count"],
            "execution_time_ms": data["execution_time_ms"],
        }


def _execute_on_databricks(
    sql: str,
    workspace_client: WorkspaceClient | None = None,
    warehouse_id: str | None = None,
) -> dict:
    """Execute SQL on Databricks via the SDK (synchronous).
    Uses the provided workspace_client/warehouse_id if given,
    otherwise falls back to the system identity.
    """
    wc = workspace_client or _workspace_client
    wh_id = warehouse_id or _warehouse_id
    if wc is None:
        raise HTTPException(status_code=400, detail="No Databricks workspace connected")
    if not wh_id:
        raise HTTPException(status_code=400, detail="No SQL warehouse selected")
    from databricks.sdk.service.sql import StatementState

    try:
        response = wc.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=wh_id,
            wait_timeout="30s",
        )
    except Exception as e:
        raise _databricks_error_to_http(e)
    state = response.status.state if response.status else None
    if state == StatementState.FAILED:
        error_msg = "Unknown error"
        if response.status.error:
            error_msg = response.status.error.message or str(response.status.error)
        raise HTTPException(
            status_code=502, detail=f"Databricks execution failed: {error_msg}"
        )
    if state == StatementState.CANCELED:
        raise HTTPException(
            status_code=502, detail="Databricks execution was cancelled"
        )
    if state != StatementState.SUCCEEDED:
        raise HTTPException(
            status_code=502, detail=f"Databricks execution in unexpected state: {state}"
        )
    # Extract columns from manifest
    columns = []
    if (
        response.manifest
        and response.manifest.schema
        and response.manifest.schema.columns
    ):
        columns = [col.name for col in response.manifest.schema.columns]
    # Extract rows from result
    rows = []
    if response.result and response.result.data_array:
        rows = response.result.data_array[:MAX_RESULT_ROWS]
    row_count = len(rows)
    if response.manifest and response.manifest.total_row_count is not None:
        row_count = response.manifest.total_row_count
    return {
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "execution_time_ms": None,  # SDK doesn't report this; caller uses wall-clock
    }


@app.post("/api/query")
async def execute_query(
    body: QueryExecutionRequest, user: auth.UserContext = Depends(verify_token)
):
    correlation_id = str(uuid.uuid4())

    # 1. Parse & analyze SQL
    analysis = query_analyzer.analyze_query(body.sql)

    if analysis.error:
        raise HTTPException(
            status_code=400, detail=f"SQL analysis failed: {analysis.error}"
        )

    # 2. Reject non-SELECT statements (security boundary)
    if analysis.statement_type != "SELECT":
        raise HTTPException(
            status_code=400,
            detail=f"Only SELECT statements are supported, got {analysis.statement_type}",
        )

    # 2b. User table-level permission check (SDK users only)
    if not user.is_admin and analysis.tables:
        denied = permissions.check_user_table_access(
            analysis.tables, user.session.workspace_client
        )
        if denied:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied to table(s): {', '.join(denied)}",
            )

    # 3. Fetch table metadata
    try:
        table_metadata = catalog_service.get_tables_metadata(
            analysis.tables, _workspace_client
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _databricks_error_to_http(exc)

    # 4. Load routing settings and probe engine states for scoring
    try:
        settings_row = db.fetch_one("SELECT * FROM routing_settings WHERE id = 1")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load routing settings: {exc}"
        )
    r_settings = (
        routing_engine.RoutingSettings(
            fit_weight=settings_row["fit_weight"],
            cost_weight=settings_row["cost_weight"],
            running_bonus_duckdb=settings_row["running_bonus_duckdb"],
            running_bonus_databricks=settings_row["running_bonus_databricks"],
        )
        if settings_row
        else routing_engine.RoutingSettings()
    )

    # Probe DuckDB: any active engine responding to health?
    duckdb_running = False
    async with httpx.AsyncClient(timeout=2.0) as probe:
        for eng in engines_api.get_duckdb_engines():
            try:
                resp = await probe.get(f"{engines_api.engine_url(eng)}/health")
                resp.raise_for_status()
                duckdb_running = True
                break
            except Exception:
                continue

    # Databricks warehouse state: check if selected warehouse is RUNNING
    databricks_running = False
    if _workspace_client and _warehouse_id:
        try:
            wh = _workspace_client.warehouses.get(_warehouse_id)
            databricks_running = (
                wh.state is not None and wh.state.value.upper() == "RUNNING"
            )
        except Exception:
            pass  # Can't determine state, assume not running

    e_states = routing_engine.EngineStates(
        duckdb_running=duckdb_running,
        databricks_running=databricks_running,
    )

    # 5. Route
    try:
        routing_result = routing_engine.route_query(
            analysis,
            table_metadata,
            body.routing_mode,
            settings=r_settings,
            engine_states=e_states,
        )
        decision = routing_result.decision
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 6. Execute on chosen engine
    wall_start = time.monotonic()
    exec_error: Exception | None = None
    result = None
    try:
        if decision.engine == "duckdb":
            result = await _execute_on_duckdb(body.sql, analysis.tables)
        else:
            if not user.is_admin:
                result = _execute_on_databricks(
                    body.sql,
                    workspace_client=user.session.workspace_client,
                    warehouse_id=_warehouse_id,
                )
            else:
                result = _execute_on_databricks(body.sql)
    except Exception as e:
        exec_error = e
    wall_ms = round((time.monotonic() - wall_start) * 1000, 2)

    if exec_error is not None:
        # Serialize routing events collected so far for the error log
        error_events = [
            {
                "timestamp": ev.timestamp,
                "level": ev.level,
                "stage": ev.stage,
                "message": ev.message,
            }
            for ev in routing_result.events
        ]
        query_logger.submit_log(
            correlation_id=correlation_id,
            user_id=user.username,
            engine=decision.engine,
            reason=decision.reason,
            complexity_score=decision.complexity_score,
            execution_time_ms=wall_ms,
            routing_log_events=error_events,
        )
        if isinstance(exec_error, HTTPException):
            raise exec_error
        raise HTTPException(
            status_code=502,
            detail=f"Execution failed on {decision.engine}: {exec_error}",
        )

    # Use engine-reported time if available, else wall-clock
    execution_time_ms = (
        result["execution_time_ms"]
        if result["execution_time_ms"] is not None
        else wall_ms
    )

    # Add execution-phase events (after we know execution_time_ms)
    routing_result.events.append(
        routing_engine.RoutingLogEvent(
            routing_engine._ts(),
            "info",
            "execute",
            f"Submitting query to {decision.engine}",
        )
    )
    routing_result.events.append(
        routing_engine.RoutingLogEvent(
            routing_engine._ts(),
            "info",
            "complete",
            f"Query executed in {execution_time_ms}ms",
        )
    )

    events_dicts = [
        {
            "timestamp": e.timestamp,
            "level": e.level,
            "stage": e.stage,
            "message": e.message,
        }
        for e in routing_result.events
    ]

    # 6. Log (fire-and-forget, never blocks the response)
    query_logger.submit_log(
        correlation_id=correlation_id,
        user_id=user.username,
        sql=body.sql,
        status="success",
        engine=decision.engine,
        reason=decision.reason,
        complexity_score=decision.complexity_score,
        execution_time_ms=execution_time_ms,
        routing_log_events=events_dicts,
    )

    # 7. Build response (matches frontend QueryExecutionResult)
    return {
        "correlation_id": correlation_id,
        "routing_decision": {
            "engine": decision.engine,
            "engine_display_name": "DuckDB"
            if decision.engine == "duckdb"
            else "Databricks",
            "stage": decision.stage,
            "reason": decision.reason,
            "complexity_score": decision.complexity_score,
        },
        "execution": {
            "execution_time_ms": execution_time_ms,
        },
        "columns": result["columns"],
        "rows": result["rows"],
        "routing_log_events": events_dicts,
    }


@app.get("/api/query/{correlation_id}")
async def get_query(
    correlation_id: str, user: auth.UserContext = Depends(verify_token)
):
    row = db.fetch_one(
        """SELECT q.correlation_id, q.query_text, q.status, q.submitted_at, q.completed_at,
                    q.execution_time_ms, q.routing_log_events,
                    r.engine, r.reason, r.complexity_score
            FROM query_logs q
            JOIN routing_decisions r ON r.query_log_id = q.id
        WHERE q.correlation_id = %s""",
        (correlation_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Query not found")
    return {
        "correlation_id": str(row["correlation_id"]),
        "query_text": row["query_text"],
        "status": row["status"],
        "submitted_at": row["submitted_at"].isoformat(),
        "completed_at": row["completed_at"].isoformat()
        if row["completed_at"]
        else None,
        "execution_time_ms": row["execution_time_ms"],
        "routing_decision": {
            "engine": row["engine"],
            "engine_display_name": "DuckDB"
            if row["engine"] == "duckdb"
            else "Databricks",
            "reason": row["reason"],
            "complexity_score": row["complexity_score"],
        },
        "routing_log_events": row["routing_log_events"],
    }


@app.get("/api/logs")
async def get_logs(
    engine: str | None = None, user: auth.UserContext = Depends(verify_token)
):
    base_sql = """ SELECT q.correlation_id, q.query_text, q.status, q.submitted_at,
                        q.execution_time_ms,
                        r.engine, r.reason, r.complexity_score
                   FROM query_logs q
                   JOIN routing_decisions r ON r.query_log_id = q.id
                """
    if engine:
        base_sql += " WHERE r.engine = %s"
        base_sql += " ORDER BY q.submitted_at DESC LIMIT 100"
        rows = db.fetch_all(base_sql, (engine,))
    else:
        base_sql += " ORDER BY q.submitted_at DESC LIMIT 100"
        rows = db.fetch_all(base_sql)
    return [
        {
            "correlation_id": str(r["correlation_id"]),
            "timestamp": r["submitted_at"].isoformat(),
            "query_text": r["query_text"],
            "engine": r["engine"],
            "engine_display_name": "DuckDB"
            if r["engine"] == "duckdb"
            else "Databricks",
            "status": r["status"],
            "latency_ms": round(r["execution_time_ms"])
            if r["execution_time_ms"]
            else 0,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Routing rules CRUD
# ---------------------------------------------------------------------------
class CreateRoutingRule(BaseModel):
    priority: int
    condition_type: str
    condition_value: str
    target_engine: str


class UpdateRoutingRule(BaseModel):
    priority: int | None = None
    condition_type: str | None = None
    condition_value: str | None = None
    target_engine: str | None = None


@app.get("/api/routing/rules")
async def list_routing_rules(user: auth.UserContext = Depends(verify_token)):
    rows = db.fetch_all("SELECT * FROM routing_rules ORDER BY priority")
    return rows


@app.post("/api/routing/rules", status_code=201)
async def create_routing_rule(
    body: CreateRoutingRule, user: auth.UserContext = Depends(verify_token)
):
    row = db.fetch_one(
        """INSERT INTO routing_rules (priority, condition_type, condition_value, target_engine, is_system, enabled)
           VALUES (%s, %s, %s, %s, false, true)
           RETURNING *""",
        (body.priority, body.condition_type, body.condition_value, body.target_engine),
    )
    return row


@app.put("/api/routing/rules/{rule_id}")
async def update_routing_rule(
    rule_id: int,
    body: UpdateRoutingRule,
    user: auth.UserContext = Depends(verify_token),
):
    existing = db.fetch_one("SELECT * FROM routing_rules WHERE id = %s", (rule_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    if existing["is_system"]:
        raise HTTPException(status_code=403, detail="Cannot modify a system rule")
    # Build SET clause from non-None fields only
    fields = {}
    if body.priority is not None:
        fields["priority"] = body.priority
    if body.condition_type is not None:
        fields["condition_type"] = body.condition_type
    if body.condition_value is not None:
        fields["condition_value"] = body.condition_value
    if body.target_engine is not None:
        fields["target_engine"] = body.target_engine
    if not fields:
        return existing
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [rule_id]
    row = db.fetch_one(
        f"UPDATE routing_rules SET {set_clause} WHERE id = %s RETURNING *",
        tuple(values),
    )
    return row


@app.delete("/api/routing/rules/{rule_id}", status_code=204)
async def delete_routing_rule(
    rule_id: int, user: auth.UserContext = Depends(verify_token)
):
    existing = db.fetch_one("SELECT * FROM routing_rules WHERE id = %s", (rule_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    if existing["is_system"]:
        raise HTTPException(status_code=403, detail="Cannot delete a system rule")
    db.execute("DELETE FROM routing_rules WHERE id = %s", (rule_id,))
    return Response(status_code=204)


@app.put("/api/routing/rules/{rule_id}/toggle")
async def toggle_routing_rule(
    rule_id: int, user: auth.UserContext = Depends(verify_token)
):
    existing = db.fetch_one("SELECT * FROM routing_rules WHERE id = %s", (rule_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    row = db.fetch_one(
        "UPDATE routing_rules SET enabled = NOT enabled WHERE id = %s RETURNING *",
        (rule_id,),
    )
    return row


@app.post("/api/routing/rules/reset")
async def reset_routing_rules(user: auth.UserContext = Depends(verify_token)):
    db.execute("DELETE FROM routing_rules WHERE is_system = false")
    db.execute(
        """INSERT INTO routing_rules (id, priority, condition_type, condition_value, target_engine, is_system)
           VALUES
               (1, 1, 'table_type', 'VIEW', 'databricks', true),
               (2, 2, 'has_governance', 'row_filter', 'databricks', true),
               (3, 3, 'has_governance', 'column_mask', 'databricks', true),
               (4, 4, 'table_type', 'FOREIGN', 'databricks', true),
               (5, 5, 'external_access', 'false', 'databricks', true)
           ON CONFLICT DO NOTHING"""
    )
    db.execute("UPDATE routing_rules SET enabled = true WHERE is_system = true")
    rows = db.fetch_all("SELECT * FROM routing_rules ORDER BY priority")
    return rows


# ---------------------------------------------------------------------------
# Routing settings
# ---------------------------------------------------------------------------
class UpdateRoutingSettings(BaseModel):
    fit_weight: float | None = None
    cost_weight: float | None = None
    running_bonus_duckdb: float | None = None
    running_bonus_databricks: float | None = None


@app.get("/api/routing/settings")
async def get_routing_settings(user: auth.UserContext = Depends(verify_token)):
    row = db.fetch_one("SELECT * FROM routing_settings WHERE id = 1")
    if not row:
        raise HTTPException(status_code=500, detail="Routing settings not initialized")

    # Include the active (default) profile ID for frontend awareness
    default_profile = db.fetch_one(
        "SELECT id FROM routing_profiles WHERE is_default = true"
    )

    return {
        "fit_weight": row["fit_weight"],
        "cost_weight": row["cost_weight"],
        "running_bonus_duckdb": row["running_bonus_duckdb"],
        "running_bonus_databricks": row["running_bonus_databricks"],
        "active_profile_id": default_profile["id"] if default_profile else None,
    }


@app.put("/api/routing/settings")
async def update_routing_settings(
    body: UpdateRoutingSettings, user: auth.UserContext = Depends(verify_token)
):
    # Validate bonus values are non-negative
    if body.running_bonus_duckdb is not None and body.running_bonus_duckdb < 0:
        raise HTTPException(
            status_code=400, detail="running_bonus_duckdb must be non-negative"
        )
    if body.running_bonus_databricks is not None and body.running_bonus_databricks < 0:
        raise HTTPException(
            status_code=400, detail="running_bonus_databricks must be non-negative"
        )
    # Weight auto-complement logic
    fit_w = body.fit_weight
    cost_w = body.cost_weight
    if fit_w is not None and cost_w is not None:
        if abs((fit_w + cost_w) - 1.0) > 1e-9:
            raise HTTPException(
                status_code=400,
                detail="fit_weight and cost_weight must sum to 1.0",
            )
    elif fit_w is not None:
        cost_w = round(1.0 - fit_w, 10)
    elif cost_w is not None:
        fit_w = round(1.0 - cost_w, 10)
    # Build SET clause from non-None fields
    fields = {}
    if fit_w is not None:
        fields["fit_weight"] = fit_w
    if cost_w is not None:
        fields["cost_weight"] = cost_w
    if body.running_bonus_duckdb is not None:
        fields["running_bonus_duckdb"] = body.running_bonus_duckdb
    if body.running_bonus_databricks is not None:
        fields["running_bonus_databricks"] = body.running_bonus_databricks
    if not fields:
        # Nothing to update, return current settings
        return await get_routing_settings(user)
    fields["updated_at"] = "NOW()"
    set_parts = []
    values = []
    for k, v in fields.items():
        if v == "NOW()":
            set_parts.append(f"{k} = NOW()")
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    row = db.fetch_one(
        f"UPDATE routing_settings SET {', '.join(set_parts)} WHERE id = 1 RETURNING *",
        tuple(values) if values else None,
    )
    return {
        "fit_weight": row["fit_weight"],
        "cost_weight": row["cost_weight"],
        "running_bonus_duckdb": row["running_bonus_duckdb"],
        "running_bonus_databricks": row["running_bonus_databricks"],
    }
