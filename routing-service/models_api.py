"""ML models API — CRUD endpoints for trained latency prediction models."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import auth
import db
import model_inference
import model_trainer

logger = logging.getLogger("routing-service.models_api")

router = APIRouter(prefix="/api/models", tags=["models"])

MODEL_DIR = os.environ.get("MODEL_DIR", "/models/")


# --- List / detail ---


@router.get("")
async def list_models(user: auth.UserContext = Depends(auth.verify_token)):
    """List all trained models, newest first."""
    rows = db.fetch_all("SELECT * FROM models ORDER BY created_at DESC")
    return rows


# --- Train (must be before /{model_id} routes to avoid path conflicts) ---


@router.post("/train")
async def train_model_endpoint(
    user: auth.UserContext = Depends(auth.verify_token),
):
    """Train a new latency prediction model from benchmark data.

    Admin-only. Runs synchronously (training data is small, typically <1000 rows).
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        result = model_trainer.train_model(model_dir=MODEL_DIR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Training failed")
        raise HTTPException(status_code=500, detail=f"Training failed: {e}")

    return result


# --- Detail ---


@router.get("/{model_id}")
async def get_model(model_id: int, user: auth.UserContext = Depends(auth.verify_token)):
    """Get a single model by ID."""
    row = db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return row


# --- Activate / deactivate ---


@router.post("/{model_id}/activate")
async def activate_model(
    model_id: int, user: auth.UserContext = Depends(auth.verify_token)
):
    """Activate a model (deactivates any previously active model).

    Validates that the model's linked_engines are all registered in the engines table.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify model exists
    model = db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # Validate linked engines are still registered
    linked = model.get("linked_engines", [])
    if linked:
        registered = db.fetch_all(
            "SELECT id FROM engines WHERE id = ANY(%s)", (linked,)
        )
        registered_ids = {r["id"] for r in registered}
        missing = set(linked) - registered_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Model references unregistered engines: {sorted(missing)}",
            )

    # Deactivate any currently active model
    db.execute(
        "UPDATE models SET is_active = FALSE, updated_at = NOW() WHERE is_active = TRUE"
    )

    # Activate this model
    db.execute(
        "UPDATE models SET is_active = TRUE, updated_at = NOW() WHERE id = %s",
        (model_id,),
    )

    # Invalidate inference cache so next prediction picks up the new model
    model_inference.invalidate_cache()

    return db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))


@router.post("/{model_id}/deactivate")
async def deactivate_model(
    model_id: int, user: auth.UserContext = Depends(auth.verify_token)
):
    """Deactivate a model."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    model = db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    db.execute(
        "UPDATE models SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
        (model_id,),
    )

    model_inference.invalidate_cache()

    return db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))


# --- Delete ---


@router.delete("/{model_id}")
async def delete_model(
    model_id: int, user: auth.UserContext = Depends(auth.verify_token)
):
    """Delete a model record and its joblib file from disk."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    model = db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    # Delete joblib file (if it exists)
    model_path = model.get("latency_model", {}).get("model_path")
    if model_path:
        try:
            os.remove(model_path)
            logger.info("Deleted model file: %s", model_path)
        except FileNotFoundError:
            logger.warning("Model file not found (already deleted?): %s", model_path)

    db.execute("DELETE FROM models WHERE id = %s", (model_id,))

    # Invalidate cache in case the deleted model was active
    model_inference.invalidate_cache()

    return Response(status_code=204)
