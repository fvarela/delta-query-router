"""Engine registry API — database-backed engine catalog with runtime probes."""

import asyncio
import logging
import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import db
import auth
from auth import verify_token

logger = logging.getLogger("routing-service.engines")

router = APIRouter(prefix="/api/engines", tags=["engines"])


# --- Pydantic models ---


class UpdateEngine(BaseModel):
    display_name: str | None = None
    config: dict | None = None
    cost_tier: int | None = None
    is_active: bool | None = None
    lifecycle_mode: str | None = None
    idle_timeout_minutes: int | None = None


class ScaleRequest(BaseModel):
    replicas: int  # 0 = stop, 1 = start


class SyncDatabricksRequest(BaseModel):
    host: str
    warehouses: list[dict]  # [{id, name, state, cluster_size, warehouse_type}]


# --- Internal helpers (used by main.py too) ---


def _scale_deployment(deployment_name: str, replicas: int) -> None:
    """Scale a K8s Deployment to the given replica count.

    Raises HTTPException on failure.  Import of kubernetes is deferred so the
    module loads without errors outside a cluster.
    """
    from kubernetes import client as k8s_client, config as k8s_config

    try:
        k8s_config.load_incluster_config()
    except Exception:
        raise HTTPException(
            status_code=500, detail="Not running in a Kubernetes cluster"
        )

    apps_v1 = k8s_client.AppsV1Api()
    try:
        apps_v1.patch_namespaced_deployment_scale(
            name=deployment_name,
            namespace="default",
            body={"spec": {"replicas": replicas}},
        )
    except k8s_client.exceptions.ApiException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scale {deployment_name}: {e.reason}",
        )
    logger.info("Scaled %s to %d replica(s)", deployment_name, replicas)


def get_duckdb_engines() -> list[dict]:
    """Return all active DuckDB engines from the database."""
    return db.fetch_all(
        "SELECT * FROM engines WHERE engine_type = 'duckdb' AND is_active = TRUE "
        "ORDER BY cost_tier ASC"
    )


def get_all_engines() -> list[dict]:
    """Return all engines from the database."""
    return db.fetch_all("SELECT * FROM engines ORDER BY engine_type, cost_tier")


def engine_url(engine: dict) -> str:
    """Build the HTTP URL for a DuckDB engine from its k8s_service_name."""
    svc = engine.get("k8s_service_name")
    if not svc:
        raise ValueError(f"Engine {engine['id']} has no k8s_service_name")
    return f"http://{svc}:8002"


# --- Engine endpoints ---


@router.get("")
async def list_engines():
    """List all engines with live runtime status probes."""
    rows = get_all_engines()

    # Fetch latest cold start measurement per engine
    cold_starts = db.fetch_all(
        "SELECT DISTINCT ON (engine_id) engine_id, cold_start_ms, measured_at "
        "FROM engine_cold_starts ORDER BY engine_id, measured_at DESC"
    )
    cold_start_map = {r["engine_id"]: r["cold_start_ms"] for r in cold_starts}

    async def _build_entry(row: dict, client: httpx.AsyncClient) -> dict:
        entry = {
            "id": row["id"],
            "engine_type": row["engine_type"],
            "display_name": row["display_name"],
            "config": row["config"] or {},
            "is_default": False,
            "enabled": row["is_active"],
            "cost_tier": row["cost_tier"],
            "k8s_service_name": row.get("k8s_service_name"),
            "lifecycle_mode": row.get("lifecycle_mode", "always-on"),
            "idle_timeout_minutes": row.get("idle_timeout_minutes", 15),
            "created_at": row["created_at"].isoformat()
            if row.get("created_at") and hasattr(row["created_at"], "isoformat")
            else row.get("created_at"),
            "updated_at": row["updated_at"].isoformat()
            if row.get("updated_at") and hasattr(row["updated_at"], "isoformat")
            else row.get("updated_at"),
        }

        if row["engine_type"] == "duckdb" and row.get("k8s_service_name"):
            try:
                resp = await client.get(f"{engine_url(row)}/health")
                resp.raise_for_status()
                entry["runtime_state"] = "running"
            except Exception:
                entry["runtime_state"] = "stopped"
            entry["scalable"] = True
        elif row["engine_type"] == "databricks_sql":
            entry["runtime_state"] = row["config"].get("runtime_state", "unknown")
            entry["scalable"] = False
        else:
            entry["runtime_state"] = "unknown"
            entry["scalable"] = False

        # Cold start: always-on DuckDB = 0ms, others from measurements
        if row.get("lifecycle_mode") == "always-on" and row["engine_type"] == "duckdb":
            entry["cold_start_ms"] = 0
        else:
            entry["cold_start_ms"] = cold_start_map.get(row["id"])

        return entry

    async with httpx.AsyncClient(timeout=1.0) as client:
        engines = await asyncio.gather(*[_build_entry(row, client) for row in rows])

    return list(engines)


@router.get("/{engine_id}")
async def get_engine(engine_id: str):
    """Get a single engine by ID."""
    row = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Engine not found")
    return row


@router.put("/{engine_id}")
async def update_engine(engine_id: str, body: UpdateEngine):
    """Update engine fields (display_name, config, cost_tier, is_active)."""
    existing = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Engine not found")

    fields: dict = {}
    if body.display_name is not None:
        fields["display_name"] = body.display_name
    if body.config is not None:
        # Merge with existing config rather than replacing
        import json

        merged = {**(existing["config"] or {}), **body.config}
        fields["config"] = json.dumps(merged)
    if body.cost_tier is not None:
        if not (1 <= body.cost_tier <= 10):
            raise HTTPException(status_code=400, detail="cost_tier must be 1-10")
        fields["cost_tier"] = body.cost_tier
    if body.is_active is not None:
        fields["is_active"] = body.is_active
    if body.lifecycle_mode is not None:
        if body.lifecycle_mode not in ("always-on", "on-demand"):
            raise HTTPException(status_code=400, detail="lifecycle_mode must be 'always-on' or 'on-demand'")
        fields["lifecycle_mode"] = body.lifecycle_mode
    if body.idle_timeout_minutes is not None:
        if body.idle_timeout_minutes < 1:
            raise HTTPException(status_code=400, detail="idle_timeout_minutes must be >= 1")
        fields["idle_timeout_minutes"] = body.idle_timeout_minutes

    if not fields:
        return existing

    set_parts = [f"{k} = %s" for k in fields]
    set_parts.append("updated_at = NOW()")
    values = list(fields.values()) + [engine_id]
    updated = db.fetch_one(
        f"UPDATE engines SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
        tuple(values),
    )

    # Auto-scale DuckDB deployments when is_active changes
    if (
        body.is_active is not None
        and body.is_active != existing["is_active"]
        and existing["engine_type"] == "duckdb"
        and existing.get("k8s_service_name")
    ):
        replicas = 1 if body.is_active else 0
        try:
            _scale_deployment(existing["k8s_service_name"], replicas)
        except HTTPException as exc:
            # Log but don't fail the update — DB state is already committed
            logger.warning(
                "Engine %s toggled is_active=%s but K8s scaling failed: %s",
                engine_id,
                body.is_active,
                exc.detail,
            )

    return updated


@router.post("/{engine_id}/scale")
async def scale_engine(engine_id: str, body: ScaleRequest):
    """Scale a DuckDB worker up (replicas=1) or down (replicas=0)."""
    engine = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not engine:
        raise HTTPException(status_code=404, detail="Engine not found")
    if engine["engine_type"] != "duckdb":
        raise HTTPException(status_code=400, detail="Only DuckDB engines can be scaled")
    if not engine.get("k8s_service_name"):
        raise HTTPException(status_code=400, detail="Engine has no k8s_service_name")
    if body.replicas not in (0, 1):
        raise HTTPException(status_code=400, detail="replicas must be 0 or 1")

    deployment_name = engine["k8s_service_name"]
    _scale_deployment(deployment_name, body.replicas)

    action = "started" if body.replicas == 1 else "stopped"
    return {"engine_id": engine_id, "deployment": deployment_name, "status": action}


@router.post("/{engine_id}/start")
async def start_engine(engine_id: str):
    """Start a DuckDB engine: scale to 1 replica and wait for health."""
    engine = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not engine:
        raise HTTPException(status_code=404, detail="Engine not found")
    if engine["engine_type"] != "duckdb":
        raise HTTPException(status_code=400, detail="Only DuckDB engines can be started")
    if not engine.get("k8s_service_name"):
        raise HTTPException(status_code=400, detail="Engine has no k8s_service_name")

    deployment_name = engine["k8s_service_name"]
    _scale_deployment(deployment_name, 1)

    # Poll health until ready (max 60s)
    url = engine_url(engine) + "/health"
    async with httpx.AsyncClient(timeout=2.0) as client:
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return {"engine_id": engine_id, "status": "running"}
            except Exception:
                pass

    return {"engine_id": engine_id, "status": "starting", "message": "Health check not yet passing after 60s"}


@router.post("/{engine_id}/stop")
async def stop_engine(engine_id: str):
    """Stop a DuckDB engine: scale to 0 replicas."""
    engine = db.fetch_one("SELECT * FROM engines WHERE id = %s", (engine_id,))
    if not engine:
        raise HTTPException(status_code=404, detail="Engine not found")
    if engine["engine_type"] != "duckdb":
        raise HTTPException(status_code=400, detail="Only DuckDB engines can be stopped")
    if not engine.get("k8s_service_name"):
        raise HTTPException(status_code=400, detail="Engine has no k8s_service_name")

    _scale_deployment(engine["k8s_service_name"], 0)
    return {"engine_id": engine_id, "status": "stopped"}


@router.post("/sync-databricks")
async def sync_databricks_engines(body: SyncDatabricksRequest):
    """Upsert Databricks warehouses into the engines table."""
    synced = []
    for wh in body.warehouses:
        wh_id = wh.get("id")
        if not wh_id:
            continue
        engine_id = f"databricks-{wh_id}"

        # Map warehouse state to runtime_state
        state_str = (wh.get("state") or "UNKNOWN").upper()
        if state_str == "RUNNING":
            runtime_state = "running"
        elif state_str in ("STARTING", "RESUMING"):
            runtime_state = "starting"
        elif state_str in ("STOPPED", "STOPPING", "DELETED", "DELETING"):
            runtime_state = "stopped"
        else:
            runtime_state = "unknown"

        import json

        config = json.dumps(
            {
                "warehouse_id": wh_id,
                "cluster_size": wh.get("cluster_size", ""),
                "warehouse_type": wh.get("warehouse_type", ""),
                "runtime_state": runtime_state,
            }
        )

        row = db.fetch_one(
            """
            INSERT INTO engines (id, engine_type, display_name, config, cost_tier)
            VALUES (%s, 'databricks_sql', %s, %s, 7)
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                config = EXCLUDED.config,
                updated_at = NOW()
            RETURNING *
            """,
            (engine_id, wh.get("name", wh_id), config),
        )
        synced.append(row)

    return {"synced": len(synced), "engines": synced}


# --- Cold start measurement endpoints ---

_measuring: set[str] = set()
_measuring_lock = threading.Lock()


def _do_measure(engine_id: str):
    """Background thread target for cold start measurement."""
    import cold_start_measure
    try:
        cold_start_measure.measure_cold_start(engine_id)
    except Exception as e:
        logger.error("Cold start measurement failed for %s: %s", engine_id, e)
    finally:
        with _measuring_lock:
            _measuring.discard(engine_id)


@router.post("/{engine_id}/measure-cold-start", status_code=202)
async def measure_cold_start(engine_id: str, user: auth.UserContext = Depends(verify_token)):
    """Trigger cold start measurement for an engine (admin-only)."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    # Verify engine exists
    engine = db.fetch_one("SELECT id FROM engines WHERE id = %s", (engine_id,))
    if not engine:
        raise HTTPException(status_code=404, detail="Engine not found")

    with _measuring_lock:
        if engine_id in _measuring:
            raise HTTPException(status_code=409, detail="Measurement already in progress")
        _measuring.add(engine_id)

    thread = threading.Thread(target=_do_measure, args=(engine_id,), daemon=True)
    thread.start()
    return {"status": "measuring", "engine_id": engine_id}


@router.get("/{engine_id}/cold-start")
async def get_cold_start(engine_id: str):
    """Get latest cold start measurement for an engine."""
    row = db.fetch_one(
        """
        SELECT cold_start_ms, measured_at
        FROM engine_cold_starts
        WHERE engine_id = %s
        ORDER BY measured_at DESC
        LIMIT 1
        """,
        (engine_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="No cold start measurement found")

    with _measuring_lock:
        measuring = engine_id in _measuring

    return {
        "engine_id": engine_id,
        "cold_start_ms": row["cold_start_ms"],
        "measured_at": row["measured_at"].isoformat(),
        "measuring": measuring,
    }


@router.get("/cold-starts/all")
async def get_all_cold_starts():
    """Get latest cold start measurement for all engines."""
    rows = db.fetch_all(
        """
        SELECT DISTINCT ON (engine_id) engine_id, cold_start_ms, measured_at
        FROM engine_cold_starts
        ORDER BY engine_id, measured_at DESC
        """
    )
    with _measuring_lock:
        measuring_set = set(_measuring)

    return [
        {
            "engine_id": r["engine_id"],
            "cold_start_ms": r["cold_start_ms"],
            "measured_at": r["measured_at"].isoformat(),
            "measuring": r["engine_id"] in measuring_set,
        }
        for r in rows
    ]
