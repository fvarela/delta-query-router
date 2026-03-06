import os
import httpx
import psycopg2
from fastapi import FastAPI

app = FastAPI()

# Backend connection config from environment
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "deltarouter")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "delta")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
DUCKDB_WORKER_URL = os.environ.get("DUCKDB_WORKER_URL", "http://localhost:8002")

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