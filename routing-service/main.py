import os
import secrets
import httpx
import psycopg2
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel

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

class LoginRequest(BaseModel):
    username: str
    password: str

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

@app.get("/api/settings/databricks")
async def get_databricks_settings(username: str = Depends(verify_token)):
    return {"configured": False}

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
    return backends