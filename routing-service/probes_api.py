"""Storage latency probes API — measure I/O latency from DuckDB to cloud storage."""

import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db
import engines_api

logger = logging.getLogger("routing-service.probes")

router = APIRouter(prefix="/api/latency-probes", tags=["latency-probes"])


# --- Internal helpers ---


def _get_probe_targets() -> list[dict]:
    """Get one representative table per distinct storage_location from cache.

    Returns list of {storage_location, table_name} dicts.
    """
    return db.fetch_all(
        """
        SELECT DISTINCT ON (storage_location)
            storage_location, table_name
        FROM table_metadata_cache
        WHERE storage_location IS NOT NULL
          AND storage_location != ''
          AND external_engine_read_support = TRUE
        ORDER BY storage_location, cached_at DESC
        """
    )


async def _probe_storage(
    engine: dict,
    table_name: str,
    databricks_host: str,
    databricks_token: str,
) -> dict:
    """Probe a single storage location via a DuckDB engine.

    Returns {probe_time_ms, bytes_read, error}.
    """
    url = engines_api.engine_url(engine)
    payload = {
        "sql": f"SELECT * FROM {table_name} LIMIT 1",
        "tables": [table_name],
        "databricks_host": databricks_host,
        "databricks_token": databricks_token,
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{url}/query", json=payload)
        probe_ms = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return {"probe_time_ms": probe_ms, "bytes_read": None, "error": str(detail)}

        return {"probe_time_ms": probe_ms, "bytes_read": None, "error": None}
    except Exception as e:
        probe_ms = (time.perf_counter() - t0) * 1000
        return {"probe_time_ms": probe_ms, "bytes_read": None, "error": str(e)}


# --- Endpoints ---


@router.post("/run")
async def run_probes():
    """Run storage latency probes for all cached storage locations."""
    import main as _main

    if not _main._databricks_host or not _main._databricks_token:
        raise HTTPException(
            status_code=400,
            detail="Databricks not configured — probes require credential vending",
        )

    targets = _get_probe_targets()
    if not targets:
        return {
            "probes": [],
            "message": "No cached tables with storage locations found",
        }

    # Use the first running DuckDB engine
    duckdb_engines = engines_api.get_duckdb_engines()
    if not duckdb_engines:
        raise HTTPException(status_code=400, detail="No active DuckDB engines")

    # Find first running engine
    running_engine = None
    async with httpx.AsyncClient(timeout=3.0) as probe_client:
        for eng in duckdb_engines:
            try:
                url = engines_api.engine_url(eng)
                resp = await probe_client.get(f"{url}/health")
                resp.raise_for_status()
                running_engine = eng
                break
            except Exception:
                continue

    if not running_engine:
        raise HTTPException(
            status_code=503,
            detail="No DuckDB worker is currently running",
        )

    engine_id = running_engine["id"]
    results = []

    for target in targets:
        result = await _probe_storage(
            running_engine,
            target["table_name"],
            _main._databricks_host,
            _main._databricks_token,
        )

        if result["error"] is None:
            db.execute(
                "INSERT INTO storage_latency_probes "
                "(storage_location, engine_id, probe_time_ms, bytes_read) "
                "VALUES (%s, %s, %s, %s)",
                (
                    target["storage_location"],
                    engine_id,
                    result["probe_time_ms"],
                    result["bytes_read"],
                ),
            )

        results.append(
            {
                "storage_location": target["storage_location"],
                "table_name": target["table_name"],
                "engine_id": engine_id,
                "probe_time_ms": round(result["probe_time_ms"], 2),
                "bytes_read": result["bytes_read"],
                "error": result["error"],
            }
        )

    return {"probes": results}


@router.get("")
async def list_probes(engine_id: str | None = None):
    """Return latest probe per (storage_location, engine_id) pair."""
    if engine_id:
        return db.fetch_all(
            """
            SELECT DISTINCT ON (storage_location, engine_id)
                id, storage_location, engine_id, probe_time_ms, bytes_read, measured_at
            FROM storage_latency_probes
            WHERE engine_id = %s
            ORDER BY storage_location, engine_id, measured_at DESC
            """,
            (engine_id,),
        )
    return db.fetch_all(
        """
        SELECT DISTINCT ON (storage_location, engine_id)
            id, storage_location, engine_id, probe_time_ms, bytes_read, measured_at
        FROM storage_latency_probes
        ORDER BY storage_location, engine_id, measured_at DESC
        """
    )
