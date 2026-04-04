"""ML model inference — load active model, predict per-engine latency.

Module-level cache keeps the active sklearn model in memory.  The cache
is invalidated when a model is activated/deactivated (call invalidate_cache()).

Public API:
    predict(analysis, table_metadata, engine_type, cost_tier) -> float | None
    predict_for_engines(analysis, table_metadata, engines) -> dict[str, float] | None
    get_active_model() -> dict | None
    invalidate_cache()
"""

from __future__ import annotations

import logging
from typing import Any

import joblib

import db
from query_analyzer import QueryAnalysis
from catalog_service import TableMetadata
from feature_builder import build_feature_vector, feature_dict_to_array

logger = logging.getLogger("routing-service.model_inference")

# ── Module-level cache ──────────────────────────────────────────────────────
_cached_model: Any = None  # sklearn estimator
_cached_model_id: int | None = None
_cached_model_record: dict | None = None


def get_active_model() -> dict | None:
    """Fetch the currently active model record from the DB, or None."""
    return db.fetch_one("SELECT * FROM models WHERE is_active = TRUE LIMIT 1")


def load_model(model_record: dict) -> Any:
    """Load a sklearn model from disk given its DB record.

    Returns the loaded estimator and updates the module cache.
    """
    global _cached_model, _cached_model_id, _cached_model_record

    model_path = model_record["latency_model"]["model_path"]
    logger.info("Loading model id=%s from %s", model_record["id"], model_path)
    estimator = joblib.load(model_path)

    _cached_model = estimator
    _cached_model_id = model_record["id"]
    _cached_model_record = model_record
    return estimator


def invalidate_cache() -> None:
    """Clear the cached model — forces reload on next predict() call."""
    global _cached_model, _cached_model_id, _cached_model_record
    _cached_model = None
    _cached_model_id = None
    _cached_model_record = None
    logger.info("Model cache invalidated")


def _ensure_model_loaded() -> Any | None:
    """Return the cached model, reloading if needed.  None if no active model."""
    global _cached_model, _cached_model_id

    active = get_active_model()
    if active is None:
        # No active model — clear cache if stale
        if _cached_model is not None:
            invalidate_cache()
        return None

    if _cached_model_id == active["id"]:
        # Already loaded
        return _cached_model

    # Different model activated — reload
    return load_model(active)


def predict(
    analysis: QueryAnalysis,
    table_metadata: dict[str, TableMetadata],
    engine_type: str,
    cost_tier: int,
) -> float | None:
    """Predict compute time (ms) for a single engine.

    Returns None if no active model is available.
    """
    model = _ensure_model_loaded()
    if model is None:
        return None

    features = build_feature_vector(analysis, table_metadata, engine_type, cost_tier)
    array = feature_dict_to_array(features)
    prediction = model.predict([array])[0]
    # Clamp to non-negative
    return max(0.0, float(prediction))


def predict_for_engines(
    analysis: QueryAnalysis,
    table_metadata: dict[str, TableMetadata],
    engines: list[dict],
) -> dict[str, float] | None:
    """Predict compute time for each engine.

    Args:
        analysis: Parsed query analysis.
        table_metadata: Table name -> TableMetadata map.
        engines: List of engine dicts with keys 'id', 'engine_type', 'cost_tier'.

    Returns:
        {engine_id: predicted_compute_ms} or None if no active model.
    """
    model = _ensure_model_loaded()
    if model is None:
        return None

    # Check that model covers all engines
    if _cached_model_record is not None:
        linked = set(_cached_model_record.get("linked_engines", []))
        engine_ids = {e["id"] for e in engines}
        if not engine_ids.issubset(linked):
            logger.info(
                "Active model (id=%s) doesn't cover engines %s (linked: %s), skipping",
                _cached_model_id,
                engine_ids - linked,
                linked,
            )
            return None

    predictions: dict[str, float] = {}
    for engine in engines:
        features = build_feature_vector(
            analysis,
            table_metadata,
            engine["engine_type"],
            engine["cost_tier"],
        )
        array = feature_dict_to_array(features)
        pred = model.predict([array])[0]
        predictions[engine["id"]] = max(0.0, float(pred))

    return predictions
