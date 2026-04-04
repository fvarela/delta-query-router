"""Tests for model_inference module."""

from unittest.mock import patch, MagicMock
import numpy as np

import model_inference
from query_analyzer import QueryAnalysis
from catalog_service import TableMetadata


def _make_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        statement_type="SELECT",
        tables=["cat.sch.t1"],
        num_tables=1,
        num_joins=0,
        num_aggregations=0,
        num_subqueries=0,
        has_group_by=False,
        has_order_by=False,
        has_limit=False,
        has_window_functions=False,
        num_columns_selected=3,
        complexity_score=1.0,
        error=None,
    )


def _make_metadata() -> dict[str, TableMetadata]:
    return {
        "cat.sch.t1": TableMetadata(
            full_name="cat.sch.t1",
            table_type="MANAGED",
            data_source_format="DELTA",
            storage_location="abfss://c@a.dfs.core.windows.net/p",
            size_bytes=5000,
            has_rls=False,
            has_column_masking=False,
            external_engine_read_support=True,
            cached=True,
        )
    }


def _make_model_record(model_id: int = 1, linked_engines: list[str] | None = None):
    return {
        "id": model_id,
        "linked_engines": linked_engines or ["duckdb-1", "databricks-1"],
        "latency_model": {
            "r_squared": 0.85,
            "mae_ms": 120.0,
            "model_path": "/models/model_1.joblib",
        },
        "training_queries": 50,
        "is_active": True,
    }


def _make_mock_estimator(return_value: float = 150.0):
    """Create a mock sklearn estimator with .predict()."""
    estimator = MagicMock()
    estimator.predict.return_value = np.array([return_value])
    return estimator


class TestGetActiveModel:
    @patch("model_inference.db.fetch_one", return_value=None)
    def test_no_active_model(self, mock_fetch):
        result = model_inference.get_active_model()
        assert result is None

    @patch("model_inference.db.fetch_one")
    def test_active_model_returned(self, mock_fetch):
        record = _make_model_record()
        mock_fetch.return_value = record
        result = model_inference.get_active_model()
        assert result == record


class TestPredict:
    def setup_method(self):
        model_inference.invalidate_cache()

    @patch("model_inference.db.fetch_one", return_value=None)
    def test_no_active_model_returns_none(self, mock_fetch):
        result = model_inference.predict(
            _make_analysis(), _make_metadata(), "duckdb", 3
        )
        assert result is None

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_with_active_model_returns_prediction(self, mock_fetch, mock_load):
        mock_fetch.return_value = _make_model_record()
        mock_load.return_value = _make_mock_estimator(200.0)

        result = model_inference.predict(
            _make_analysis(), _make_metadata(), "duckdb", 3
        )
        assert result == 200.0

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_negative_prediction_clamped_to_zero(self, mock_fetch, mock_load):
        mock_fetch.return_value = _make_model_record()
        mock_load.return_value = _make_mock_estimator(-50.0)

        result = model_inference.predict(
            _make_analysis(), _make_metadata(), "duckdb", 3
        )
        assert result == 0.0


class TestPredictForEngines:
    def setup_method(self):
        model_inference.invalidate_cache()

    @patch("model_inference.db.fetch_one", return_value=None)
    def test_no_active_model_returns_none(self, mock_fetch):
        engines = [{"id": "duckdb-1", "engine_type": "duckdb", "cost_tier": 3}]
        result = model_inference.predict_for_engines(
            _make_analysis(), _make_metadata(), engines
        )
        assert result is None

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_with_active_model(self, mock_fetch, mock_load):
        mock_fetch.return_value = _make_model_record(
            linked_engines=["duckdb-1", "databricks-1"]
        )
        mock_load.return_value = _make_mock_estimator(100.0)

        engines = [
            {"id": "duckdb-1", "engine_type": "duckdb", "cost_tier": 3},
            {"id": "databricks-1", "engine_type": "databricks", "cost_tier": 7},
        ]
        result = model_inference.predict_for_engines(
            _make_analysis(), _make_metadata(), engines
        )
        assert result is not None
        assert "duckdb-1" in result
        assert "databricks-1" in result
        assert all(v >= 0 for v in result.values())

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_engine_not_covered_by_model(self, mock_fetch, mock_load):
        """If engines include one not in linked_engines, return None."""
        mock_fetch.return_value = _make_model_record(linked_engines=["duckdb-1"])
        mock_load.return_value = _make_mock_estimator(100.0)

        engines = [
            {"id": "duckdb-1", "engine_type": "duckdb", "cost_tier": 3},
            {"id": "databricks-1", "engine_type": "databricks", "cost_tier": 7},
        ]
        result = model_inference.predict_for_engines(
            _make_analysis(), _make_metadata(), engines
        )
        assert result is None


class TestCacheManagement:
    def setup_method(self):
        model_inference.invalidate_cache()

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_model_loaded_once_and_cached(self, mock_fetch, mock_load):
        record = _make_model_record()
        mock_fetch.return_value = record
        estimator = _make_mock_estimator(100.0)
        mock_load.return_value = estimator

        # First call loads the model
        model_inference.predict(_make_analysis(), _make_metadata(), "duckdb", 3)
        assert mock_load.call_count == 1

        # Second call uses cache
        model_inference.predict(_make_analysis(), _make_metadata(), "duckdb", 3)
        assert mock_load.call_count == 1  # not loaded again

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_model_id_change_triggers_reload(self, mock_fetch, mock_load):
        record1 = _make_model_record(model_id=1)
        record2 = _make_model_record(model_id=2)
        mock_load.return_value = _make_mock_estimator(100.0)

        # Load model 1
        mock_fetch.return_value = record1
        model_inference.predict(_make_analysis(), _make_metadata(), "duckdb", 3)
        assert mock_load.call_count == 1

        # Switch to model 2
        mock_fetch.return_value = record2
        model_inference.predict(_make_analysis(), _make_metadata(), "duckdb", 3)
        assert mock_load.call_count == 2

    def test_invalidate_clears_state(self):
        model_inference._cached_model = "something"
        model_inference._cached_model_id = 99
        model_inference._cached_model_record = {"id": 99}

        model_inference.invalidate_cache()

        assert model_inference._cached_model is None
        assert model_inference._cached_model_id is None
        assert model_inference._cached_model_record is None

    @patch("model_inference.joblib.load")
    @patch("model_inference.db.fetch_one")
    def test_active_model_disappears_clears_cache(self, mock_fetch, mock_load):
        """If a model was cached but no active model exists, cache is cleared."""
        record = _make_model_record()
        mock_fetch.return_value = record
        mock_load.return_value = _make_mock_estimator(100.0)

        # Load model
        model_inference.predict(_make_analysis(), _make_metadata(), "duckdb", 3)
        assert model_inference._cached_model is not None

        # Now no active model
        mock_fetch.return_value = None
        result = model_inference.predict(
            _make_analysis(), _make_metadata(), "duckdb", 3
        )
        assert result is None
        assert model_inference._cached_model is None
