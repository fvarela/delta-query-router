"""Routing profiles API — named routing configurations with full CRUD."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

import db

logger = logging.getLogger("routing-service.routing-profiles")

router = APIRouter(prefix="/api/routing/profiles", tags=["routing-profiles"])

# --- Constants ---

VALID_ROUTING_MODES = {"single", "smart", "benchmark"}
VALID_ROUTING_PRIORITIES = {0, 0.5, 1}


# --- Pydantic models ---


class RoutingConfig(BaseModel):
    routingMode: str = "single"
    singleEngineId: str | None = None
    activeModelId: int | None = None
    enabledEngineIds: list[str] = []
    routingPriority: float = 0.5
    workspaceBinding: dict[str, Any] | None = None
    warehouseMappings: list[Any] = []

    @field_validator("routingMode")
    @classmethod
    def validate_routing_mode(cls, v: str) -> str:
        if v not in VALID_ROUTING_MODES:
            raise ValueError(f"routingMode must be one of {VALID_ROUTING_MODES}")
        return v

    @field_validator("routingPriority")
    @classmethod
    def validate_routing_priority(cls, v: float) -> float:
        if v not in VALID_ROUTING_PRIORITIES:
            raise ValueError(
                f"routingPriority must be one of {VALID_ROUTING_PRIORITIES}"
            )
        return v


class ProfileCreate(BaseModel):
    name: str
    config: RoutingConfig = RoutingConfig()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()


class ProfileUpdate(BaseModel):
    name: str | None = None
    config: RoutingConfig | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name must not be empty")
        return v.strip() if v is not None else v


# --- Helpers ---


def _format_profile(row: dict) -> dict:
    """Format a DB row into an API response."""
    return {
        "id": row["id"],
        "name": row["name"],
        "is_default": row["is_default"],
        "config": row["config"]
        if isinstance(row["config"], dict)
        else json.loads(row["config"]),
        "created_at": row["created_at"].isoformat()
        if hasattr(row.get("created_at"), "isoformat")
        else row.get("created_at"),
        "updated_at": row["updated_at"].isoformat()
        if hasattr(row.get("updated_at"), "isoformat")
        else row.get("updated_at"),
    }


# --- Endpoints ---


@router.get("")
async def list_profiles():
    """List all routing profiles."""
    rows = db.fetch_all("SELECT * FROM routing_profiles ORDER BY name")
    return [_format_profile(r) for r in rows]


@router.post("", status_code=201)
async def create_profile(body: ProfileCreate):
    """Create a new routing profile."""
    config_json = json.dumps(body.config.model_dump())
    row = db.fetch_one(
        "INSERT INTO routing_profiles (name, config) VALUES (%s, %s) RETURNING *",
        (body.name, config_json),
    )
    return _format_profile(row)


@router.get("/{profile_id}")
async def get_profile(profile_id: int):
    """Get a single routing profile."""
    row = db.fetch_one("SELECT * FROM routing_profiles WHERE id = %s", (profile_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _format_profile(row)


@router.put("/{profile_id}")
async def update_profile(profile_id: int, body: ProfileUpdate):
    """Update a routing profile's name and/or config."""
    existing = db.fetch_one(
        "SELECT * FROM routing_profiles WHERE id = %s", (profile_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.config is not None:
        fields["config"] = json.dumps(body.config.model_dump())

    if not fields:
        return _format_profile(existing)

    set_parts = [f"{k} = %s" for k in fields]
    set_parts.append("updated_at = NOW()")
    values = list(fields.values()) + [profile_id]
    row = db.fetch_one(
        f"UPDATE routing_profiles SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
        tuple(values),
    )
    return _format_profile(row)


@router.delete("/{profile_id}")
async def delete_profile(profile_id: int):
    """Delete a routing profile. Cannot delete the default profile."""
    existing = db.fetch_one(
        "SELECT * FROM routing_profiles WHERE id = %s", (profile_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")
    if existing["is_default"]:
        raise HTTPException(status_code=400, detail="Cannot delete the default profile")
    db.execute("DELETE FROM routing_profiles WHERE id = %s", (profile_id,))
    return {"deleted": True, "id": profile_id}


@router.put("/{profile_id}/default")
async def set_default_profile(profile_id: int):
    """Set a profile as the default. Clears the old default."""
    existing = db.fetch_one(
        "SELECT * FROM routing_profiles WHERE id = %s", (profile_id,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Clear old default and set new one in a single transaction
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE routing_profiles SET is_default = FALSE WHERE is_default = TRUE"
            )
            cur.execute(
                "UPDATE routing_profiles SET is_default = TRUE, updated_at = NOW() "
                "WHERE id = %s",
                (profile_id,),
            )

    row = db.fetch_one("SELECT * FROM routing_profiles WHERE id = %s", (profile_id,))
    return _format_profile(row)
