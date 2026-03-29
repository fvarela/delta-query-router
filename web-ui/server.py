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


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_routing_service(path: str, request: Request):
    """Forward all /api/* requests to routing-service."""
    url = f"{ROUTING_SERVICE_URL}/api/{path}"
    if request.query_params:
        url += f"?{request.query_params}"
    headers = {}
    if "authorization" in request.headers:
        headers["Authorization"] = request.headers["authorization"]
    if "content-type" in request.headers:
        headers["Content-Type"] = request.headers["content-type"]
    body = await request.body() if request.method in ("POST", "PUT", "DELETE") else None

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.request(
                request.method, url, headers=headers, content=body
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type="application/json",
        )
    except httpx.ConnectError:
        return Response(
            content=b'{"detail": "routing-service unavailable"}',
            status_code=502,
            media_type="application/json",
        )


# --- Static file serving (single page, no SPA fallback) ---
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
