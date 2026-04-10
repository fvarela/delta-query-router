"""Model trainer — reads benchmark data, builds features, trains a model.

Public API:
    train_model(model_dir: str = "/models/") -> dict
        Reads benchmark_results (joined with collection_queries and engines),
        builds feature vectors, trains a RandomForestRegressor, computes
        hold-out metrics, saves the model to disk, and writes a record to
        the models table.  Returns the new model record dict.

Raises ValueError if fewer than 10 valid training samples are available.
"""

from __future__ import annotations

import json
import logging
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

import db
import query_analyzer
import feature_builder

logger = logging.getLogger("routing-service.model_trainer")

MIN_TRAINING_SAMPLES = 10


def _fetch_training_data() -> list[dict]:
    """Fetch benchmark results joined with query text and engine info.

    Returns list of dicts with keys:
        execution_time_ms, engine_id, sql_text, engine_type, cost_tier
    """
    return db.fetch_all(
        """
        SELECT br.execution_time_ms,
               br.engine_id,
               cq.query_text AS sql_text,
               e.engine_type,
               e.cost_tier
        FROM benchmark_results br
        JOIN collection_queries cq ON br.query_id = cq.id
        JOIN engines e ON br.engine_id = e.id
        WHERE br.execution_time_ms IS NOT NULL
        """
    )


def _compute_target(row: dict) -> float:
    """Compute training target: raw execution time (includes I/O)."""
    return row["execution_time_ms"]


def train_model(
    model_dir: str = "/models/", collection_ids: list[int] | None = None
) -> dict:
    """Train a RandomForestRegressor from benchmark data.

    1. Reads benchmark results from DB
    2. Parses each query's SQL to build feature vectors
    3. Trains 80/20 split, computes R² and MAE on hold-out
    4. Saves model to disk, writes record to models table

    Returns the new model record dict.
    Raises ValueError if fewer than MIN_TRAINING_SAMPLES are available.
    """
    rows = _fetch_training_data()
    logger.info("Fetched %d benchmark result rows for training", len(rows))

    # Build feature vectors + targets
    X_rows: list[list[float]] = []
    y_values: list[float] = []
    engine_ids: set[str] = set()
    skipped = 0

    for row in rows:
        # Parse SQL
        analysis = query_analyzer.analyze_query(row["sql_text"])
        if analysis.error is not None:
            logger.warning(
                "Skipping row (SQL parse error): engine=%s, error=%s",
                row["engine_id"],
                analysis.error,
            )
            skipped += 1
            continue

        # Build feature vector (no table metadata available from benchmarks —
        # pass empty dict; table sizes will be 0)
        features = feature_builder.build_feature_vector(
            analysis=analysis,
            table_metadata={},  # benchmark data doesn't carry table metadata
            engine_type=row["engine_type"],
            cost_tier=row["cost_tier"],
        )
        X_rows.append(feature_builder.feature_dict_to_array(features))
        y_values.append(_compute_target(row))
        engine_ids.add(row["engine_id"])

    if skipped > 0:
        logger.info("Skipped %d rows due to SQL parse errors", skipped)

    if len(X_rows) < MIN_TRAINING_SAMPLES:
        raise ValueError(
            f"Need at least {MIN_TRAINING_SAMPLES} valid training samples, "
            f"got {len(X_rows)} (from {len(rows)} total rows, {skipped} skipped)"
        )

    # Train / test split
    X = np.array(X_rows)
    y = np.array(y_values)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train model
    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    # Evaluate on hold-out set
    y_pred = model.predict(X_test)
    r_squared = float(r2_score(y_test, y_pred))
    mae_ms = float(mean_absolute_error(y_test, y_pred))

    logger.info(
        "Model trained: %d samples, R²=%.4f, MAE=%.1f ms",
        len(X_rows),
        r_squared,
        mae_ms,
    )

    # Save model to disk
    os.makedirs(model_dir, exist_ok=True)

    # Insert record to get the auto-generated ID
    linked_engines = sorted(engine_ids)
    record = db.fetch_one(
        """
        INSERT INTO models (linked_engines, latency_model, training_queries, training_collection_ids)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (
            json.dumps(linked_engines),
            json.dumps(
                {
                    "r_squared": round(r_squared, 6),
                    "mae_ms": round(mae_ms, 2),
                    "model_path": "",  # placeholder, updated below
                }
            ),
            len(X_rows),
            json.dumps(collection_ids) if collection_ids else None,
        ),
    )

    model_id = record["id"]
    model_path = os.path.join(model_dir, f"model_{model_id}.joblib")
    joblib.dump(model, model_path)

    # Update model_path in the record
    db.execute(
        """
        UPDATE models
        SET latency_model = jsonb_set(latency_model, '{model_path}', %s::jsonb),
            updated_at = NOW()
        WHERE id = %s
        """,
        (json.dumps(model_path), model_id),
    )

    # Re-fetch the final record
    final = db.fetch_one("SELECT * FROM models WHERE id = %s", (model_id,))
    logger.info("Model saved: id=%s, path=%s", model_id, model_path)
    return final
