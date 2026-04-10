"""Engine registry API — database-backed engine catalog with runtime probes."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import db

logger = logging.getLogger("routing-service.engines")

router = APIRouter(prefix="/api/engines", tags=["engines"])


# --- Pydantic models ---


class UpdateEngine(BaseModel):
    display_name: str | None = None
    config: dict | None = None
    cost_tier: int | None = None
    is_active: bool | None = None


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
    engines = []

    async with httpx.AsyncClient(timeout=3.0) as client:
        for row in rows:
            entry = {
                "id": row["id"],
                "engine_type": row["engine_type"],
                "display_name": row["display_name"],
                "config": row["config"] or {},
                "is_default": False,
                "enabled": row["is_active"],
                "cost_tier": row["cost_tier"],
                "k8s_service_name": row.get("k8s_service_name"),
                "created_at": row["created_at"].isoformat()
                if row.get("created_at") and hasattr(row["created_at"], "isoformat")
                else row.get("created_at"),
                "updated_at": row["updated_at"].isoformat()
                if row.get("updated_at") and hasattr(row["updated_at"], "isoformat")
                else row.get("updated_at"),
            }

            if row["engine_type"] == "duckdb" and row.get("k8s_service_name"):
                # Probe health endpoint
                try:
                    resp = await client.get(f"{engine_url(row)}/health")
                    resp.raise_for_status()
                    entry["runtime_state"] = "running"
                except Exception:
                    entry["runtime_state"] = "stopped"
                entry["scalable"] = True
            elif row["engine_type"] == "databricks_sql":
                # Databricks state is stored in config at sync time
                entry["runtime_state"] = row["config"].get("runtime_state", "unknown")
                entry["scalable"] = False
            else:
                entry["runtime_state"] = "unknown"
                entry["scalable"] = False

            engines.append(entry)

    return engines


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
