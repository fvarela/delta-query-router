"""Model trainer — reads benchmark data + pre-computed features, trains a model.

Public API:
    train_model(model_dir: str = "/models/") -> dict
        Reads benchmark_results joined with pre-computed query_features,
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
import feature_builder

logger = logging.getLogger("routing-service.model_trainer")

MIN_TRAINING_SAMPLES = 10


def _fetch_training_data() -> list[dict]:
    """Fetch benchmark results joined with pre-computed features and engine info.

    Returns list of dicts with keys from query_features (AST + table metadata)
    plus engine_type, cost_tier, and execution_time_ms.
    """
    return db.fetch_all(
        """
        SELECT br.execution_time_ms,
               br.engine_id,
               e.engine_type,
               e.cost_tier,
               qf.num_tables,
               qf.num_joins,
               qf.num_aggregations,
               qf.num_subqueries,
               qf.has_group_by,
               qf.has_order_by,
               qf.has_limit,
               qf.has_window_functions,
               qf.num_columns_selected,
               qf.complexity_score,
               COALESCE(qf.max_table_size_bytes, 0) AS max_table_size_bytes,
               COALESCE(qf.total_data_bytes, 0) AS total_data_bytes
        FROM benchmark_results br
        JOIN collection_queries cq ON br.query_id = cq.id
        JOIN engines e ON br.engine_id = e.id
        JOIN query_features qf ON qf.query_id = cq.id
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

    # Build feature vectors + targets from pre-computed features
    X_rows: list[list[float]] = []
    y_values: list[float] = []
    engine_ids: set[str] = set()

    for row in rows:
        features = {
            "num_tables": float(row["num_tables"]),
            "num_joins": float(row["num_joins"]),
            "num_aggregations": float(row["num_aggregations"]),
            "num_subqueries": float(row["num_subqueries"]),
            "has_group_by": 1.0 if row["has_group_by"] else 0.0,
            "has_order_by": 1.0 if row["has_order_by"] else 0.0,
            "has_limit": 1.0 if row["has_limit"] else 0.0,
            "has_window_functions": 1.0 if row["has_window_functions"] else 0.0,
            "num_columns_selected": float(row["num_columns_selected"]),
            "complexity_score": float(row["complexity_score"]),
            "max_table_size_bytes": float(row["max_table_size_bytes"]),
            "total_data_bytes": float(row["total_data_bytes"]),
            "engine_type": float(
                feature_builder._ENGINE_TYPE_MAP.get(row["engine_type"], 0)
            ),
            "cost_tier": float(row["cost_tier"]),
        }
        X_rows.append(feature_builder.feature_dict_to_array(features))
        y_values.append(_compute_target(row))
        engine_ids.add(row["engine_id"])

    if len(X_rows) < MIN_TRAINING_SAMPLES:
        raise ValueError(
            f"Need at least {MIN_TRAINING_SAMPLES} valid training samples, "
            f"got {len(X_rows)} (from {len(rows)} total rows)"
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
