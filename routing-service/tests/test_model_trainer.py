"""Tests for model_trainer module."""

import json
import os
import tempfile
from unittest.mock import patch, call

import pytest

import model_trainer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _benchmark_row(
    engine_id="duckdb-1",
    engine_type="duckdb",
    cost_tier=3,
    execution_time_ms=150.0,
    num_tables=1,
    num_joins=0,
    num_aggregations=0,
    num_subqueries=0,
    has_group_by=False,
    has_order_by=False,
    has_limit=False,
    has_window_functions=False,
    num_columns_selected=2,
    complexity_score=0.0,
    max_table_size_bytes=0,
    total_data_bytes=0,
):
    return {
        "execution_time_ms": execution_time_ms,
        "engine_id": engine_id,
        "engine_type": engine_type,
        "cost_tier": cost_tier,
        "num_tables": num_tables,
        "num_joins": num_joins,
        "num_aggregations": num_aggregations,
        "num_subqueries": num_subqueries,
        "has_group_by": has_group_by,
        "has_order_by": has_order_by,
        "has_limit": has_limit,
        "has_window_functions": has_window_functions,
        "num_columns_selected": num_columns_selected,
        "complexity_score": complexity_score,
        "max_table_size_bytes": max_table_size_bytes,
        "total_data_bytes": total_data_bytes,
    }


def _make_rows(n=20):
    """Generate n synthetic benchmark rows across 2 engines."""
    rows = []
    for i in range(n):
        engine = "duckdb-1" if i % 2 == 0 else "databricks-1"
        etype = "duckdb" if engine == "duckdb-1" else "databricks"
        cost = 3 if engine == "duckdb-1" else 7
        rows.append(
            _benchmark_row(
                engine_id=engine,
                engine_type=etype,
                cost_tier=cost,
                execution_time_ms=100.0 + i * 10,
                num_tables=1 + (i % 3),
                num_joins=i % 3,
                num_aggregations=i % 2,
                complexity_score=float(i % 3) * 3 + float(i % 2) * 2,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeTarget:
    def test_returns_execution_time(self):
        row = _benchmark_row(execution_time_ms=200.0)
        assert model_trainer._compute_target(row) == 200.0


class TestTrainModel:
    @patch("model_trainer.db.fetch_one")
    @patch("model_trainer.db.execute")
    @patch("model_trainer.db.fetch_all")
    def test_successful_training(self, mock_fetch_all, mock_execute, mock_fetch_one):
        """Train with enough data → model file + DB record."""
        rows = _make_rows(30)
        mock_fetch_all.return_value = rows

        # Mock the INSERT RETURNING and final SELECT
        mock_fetch_one.side_effect = [
            {  # INSERT RETURNING *
                "id": 42,
                "linked_engines": ["databricks-1", "duckdb-1"],
                "latency_model": {"r_squared": 0.0, "mae_ms": 0.0, "model_path": ""},
                "training_queries": 30,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
            {  # final SELECT
                "id": 42,
                "linked_engines": ["databricks-1", "duckdb-1"],
                "latency_model": {
                    "r_squared": 0.85,
                    "mae_ms": 20.0,
                    "model_path": "/tmp/test_models/model_42.joblib",
                },
                "training_queries": 30,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = model_trainer.train_model(model_dir=tmpdir)

        assert result["id"] == 42
        assert result["training_queries"] == 30

        # Verify DB calls
        mock_fetch_all.assert_called_once()  # fetch training data
        assert mock_fetch_one.call_count == 2  # INSERT RETURNING + final SELECT
        mock_execute.assert_called_once()  # UPDATE model_path

    @patch("model_trainer.db.fetch_all", return_value=[])
    def test_too_few_samples_raises(self, mock_fetch_all):
        with pytest.raises(ValueError, match="at least 10"):
            model_trainer.train_model(model_dir="/tmp/test")

    @patch("model_trainer.db.fetch_all")
    def test_fewer_than_min_raises(self, mock_fetch_all):
        """If fewer than MIN_TRAINING_SAMPLES rows, raise ValueError."""
        mock_fetch_all.return_value = _make_rows(8)
        with pytest.raises(ValueError, match="at least 10"):
            model_trainer.train_model(model_dir="/tmp/test")

    @patch("model_trainer.db.fetch_one")
    @patch("model_trainer.db.execute")
    @patch("model_trainer.db.fetch_all")
    def test_model_file_created(self, mock_all, mock_exec, mock_one):
        """Verify joblib file is written to disk."""
        mock_all.return_value = _make_rows(20)
        mock_one.side_effect = [
            {
                "id": 7,
                "linked_engines": ["databricks-1", "duckdb-1"],
                "latency_model": {"r_squared": 0.0, "mae_ms": 0.0, "model_path": ""},
                "training_queries": 20,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
            {
                "id": 7,
                "linked_engines": ["databricks-1", "duckdb-1"],
                "latency_model": {
                    "r_squared": 0.5,
                    "mae_ms": 50.0,
                    "model_path": "",
                },
                "training_queries": 20,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            model_trainer.train_model(model_dir=tmpdir)
            model_path = os.path.join(tmpdir, "model_7.joblib")
            assert os.path.exists(model_path)

    @patch("model_trainer.db.fetch_one")
    @patch("model_trainer.db.execute")
    @patch("model_trainer.db.fetch_all")
    def test_linked_engines_are_sorted(self, mock_all, mock_exec, mock_one):
        """linked_engines in DB insert should be sorted for consistency."""
        mock_all.return_value = _make_rows(20)
        mock_one.side_effect = [
            {
                "id": 1,
                "linked_engines": [],
                "latency_model": {"r_squared": 0.0, "mae_ms": 0.0, "model_path": ""},
                "training_queries": 20,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
            {
                "id": 1,
                "linked_engines": ["databricks-1", "duckdb-1"],
                "latency_model": {
                    "r_squared": 0.5,
                    "mae_ms": 50.0,
                    "model_path": "",
                },
                "training_queries": 20,
                "is_active": False,
                "created_at": "2026-04-04T10:00:00+00:00",
                "updated_at": "2026-04-04T10:00:00+00:00",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            model_trainer.train_model(model_dir=tmpdir)

        # Check the INSERT call's linked_engines arg
        insert_call = mock_one.call_args_list[0]
        linked_json = insert_call[0][1][0]  # second positional arg, first param
        linked = json.loads(linked_json)
        assert linked == sorted(linked)


class TestFetchTrainingData:
    @patch("model_trainer.db.fetch_all", return_value=[])
    def test_returns_list(self, mock_fetch):
        result = model_trainer._fetch_training_data()
        assert result == []
        mock_fetch.assert_called_once()
