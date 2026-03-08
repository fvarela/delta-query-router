"""FastAPI backend for delta-router web UI."""
import os
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
app = FastAPI(title="delta-router web-ui")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
ROUTING_SERVICE_URL = os.environ.get(
    "ROUTING_SERVICE_URL", "http://localhost:8000"
)
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
            ]:
                backend = backends.get(backend_key, {})
                if backend.get("status") == "connected":
                    result[svc_key] = {"status": "connected"}
                else:
                    detail = backend.get("error", "unhealthy")
                    result[svc_key] = {"status": "error", "detail": detail}
        except (httpx.HTTPError, httpx.ConnectError):
            pass  # Leave as "unknown"
    return result
# --- Static file serving + SPA fallback ---
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve index.html for any non-API route (SPA client-side routing)."""
        file = STATIC_DIR / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")