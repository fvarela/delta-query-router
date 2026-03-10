"""FastAPI backend for delta-router web UI."""

import os
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles


app = FastAPI(title="delta-router web-ui")

ROUTING_SERVICE_URL = os.environ.get("ROUTING_SERVICE_URL", "http://localhost:8000")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/health")
async def health():
    """K8s liveness/readiness probe."""
    return {"status": "ok"}


@app.get("/api/health/services")
async def health_services():
    """Aggregate health status of all 5 services."""
    result = {
        "web_ui": {"status": "connected"},
        "routing_service": {"status": "unknown"},
        "postgresql": {"status": "unknown"},
        "duckdb_worker": {"status": "unknown"},
        "databricks": {"status": "not_configured"},
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check routing-service health
        try:
            resp = await client.get(f"{ROUTING_SERVICE_URL}/health")
            resp.raise_for_status()
            result["routing_service"] = {"status": "connected"}
        except (httpx.HTTPError, httpx.ConnectError):
            result["routing_service"] = {"status": "error", "detail": "unreachable"}
            return result  # Can't check backends if routing-service is down

        # Check backends via routing-service
        try:
            resp = await client.get(f"{ROUTING_SERVICE_URL}/health/backends")
            resp.raise_for_status()
            backends = resp.json()
            for svc_key, backend_key in [
                ("postgresql", "postgresql"),
                ("duckdb_worker", "duckdb_worker"),
                ("databricks", "databricks"),
            ]:
                backend = backends.get(backend_key, {})
                status = backend.get("status")
                if status == "connected":
                    result[svc_key] = {"status": "connected"}
                elif status == "not_configured":
                    result[svc_key] = {"status": "not_configured"}
                else:
                    detail = backend.get("detail", "unhealthy")
                    result[svc_key] = {"status": "error", "detail": detail}

        except (httpx.HTTPError, httpx.ConnectError):
            pass  # Leave as "unknown"

    return result

@app.post("/api/auth/login")
async def proxy_login(request: Request):
    body = await request.body()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{ROUTING_SERVICE_URL}/api/auth/login", content=body, 
                                 headers={"Content-Type": "application/json"})
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/api/settings/databricks")
async def proxy_get_databricks(request: Request):
    headers = {}
    if request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/api/settings/databricks", headers=headers)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.post("/api/settings/databricks")
async def proxy_save_databricks(request: Request):
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    if request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{ROUTING_SERVICE_URL}/api/settings/databricks", content=body, headers=headers)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/api/databricks/warehouses")
async def proxy_get_warehouses(request: Request):
    headers = {}
    if request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{ROUTING_SERVICE_URL}/api/databricks/warehouses", headers=headers)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.put("/api/settings/warehouse")
async def proxy_save_warehouse(request: Request):
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    if request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.put(f"{ROUTING_SERVICE_URL}/api/settings/warehouse", content=body, headers=headers)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

# --- Static file serving (single page, no SPA fallback) ---
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
