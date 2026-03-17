import os
import secrets
import httpx
import psycopg2
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient

app = FastAPI()

# Backend connection config from environment
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "deltarouter")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "delta")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
DUCKDB_WORKER_URL = os.environ.get("DUCKDB_WORKER_URL", "http://localhost:8002")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# In-memory token store: {token_hex: username}
_active_tokens: dict[str, str] = {}

_workspace_client: WorkspaceClient | None = None
_databricks_host: str | None = None
_databricks_username: str | None = None
_warehouse_id: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str

class DatabricksCredentials(BaseModel):
    host: str
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

def _save_to_k8s_secret(creds: DatabricksCredentials):
    from kubernetes import client as k8s_client, config as k8s_config
    try:
        k8s_config.load_incluster_config()
    except Exception:
        return #Not running in cluster, skip sliently
    v1 = k8s_client.CoreV1Api()
    secret_data = {"DATABRICKS_HOST": creds.host}
    if creds.token:
        secret_data["DATABRICKS_TOKEN"] = creds.token
    if creds.client_id:
        secret_data["DATABRICKS_CLIENT_ID"] = creds.client_id
    if creds.client_secret:
        secret_data["DATABRICKS_CLIENT_SECRET"] = creds.client_secret
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

@app.post("/api/auth/login")
async def login(creds: LoginRequest):
    if creds.username != ADMIN_USERNAME or creds.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    _active_tokens[token] = creds.username
    return {"token": token}

async def verify_token(authorization: str = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    username = _active_tokens.get(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username


@app.post("/api/settings/databricks")
async def save_databricks_settings(creds: DatabricksCredentials, username: str = Depends(verify_token)):
    global _workspace_client, _databricks_host, _databricks_username
    try:
        if creds.token:
            wc = WorkspaceClient(host=creds.host, token=creds.token)
        elif creds.client_id and creds.client_secret:
            wc = WorkspaceClient(host=creds.host, client_id=creds.client_id, client_secret=creds.client_secret)
        else:
            raise HTTPException(status_code=400, detail="Provide either token or client_id+client_secret")
        me = wc.current_user.me()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect: {e}")
    _workspace_client = wc
    _databricks_host = creds.host
    _databricks_username = me.user_name
    _save_to_k8s_secret(creds)
    return {"status": "connected", "host": creds.host, "username": me.user_name}

@app.get("/api/settings/databricks")
async def get_databricks_settings(username: str = Depends(verify_token)):
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
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=3,
        )
        conn.close()
        backends["postgresql"] = {"status": "connected"}
    except Exception as e:
        backends["postgresql"] = {"status": "error", "detail": str(e)}

    # Check DuckDB Worker
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{DUCKDB_WORKER_URL}/health")
            resp.raise_for_status()
            backends["duckdb_worker"] = {"status": "connected"}
    except Exception as e:
        backends["duckdb_worker"] = {"status": "error", "detail": str(e)}
    if _workspace_client is None:
        backends["databricks"] = {"status": "not_configured"}
    else:
        try:
            _workspace_client.current_user.me()
            backends["databricks"] = {"status": "connected"}
        except Exception as e:
            backends["databricks"] = {"status": "error", "detail": str(e)}
    return backends

@app.get("/api/databricks/warehouses")
async def list_warehouses(username: str = Depends(verify_token)):
    if _workspace_client is None:
        raise HTTPException(status_code=400, detail="Databricks not configured")
    try:
        warehouses = _workspace_client.warehouses.list()
        return [
            {
                "id": wh.id,
                "name": wh.name,
                "state": wh.state.value if wh.state else "UNKNOWN"
            }
            for wh in warehouses
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list warehouses: {e}")