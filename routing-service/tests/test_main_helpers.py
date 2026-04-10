"""Tests for main.py helper functions — _load_profile_config, _profile_config_to_routing_params,
_match_warehouse_to_engine, and _databricks_error_to_http.

These are inline helpers in main.py that are testable via mocked DB/SDK calls.
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

# main.py imports many heavy modules at top level; mock them before import
# to avoid needing a real DB / Databricks connection.
import sys

# We need to import main, which triggers db.init_db-style module loads.
# The module-level code in main.py is safe because init_db is called in
# @app.on_event("startup"), not at import time.
from main import (
    _load_profile_config,
    _profile_config_to_routing_params,
    _match_warehouse_to_engine,
    _databricks_error_to_http,
)
import routing_engine


# ---------------------------------------------------------------------------
# _match_warehouse_to_engine
# ---------------------------------------------------------------------------


class TestMatchWarehouseToEngine:
    """Unit tests for warehouse → engine mapping logic."""

    def _make_wh(self, warehouse_type="PRO", cluster_size="2X-Small"):
        wh = MagicMock()
        wh.warehouse_type = MagicMock()
        wh.warehouse_type.value = warehouse_type
        wh.cluster_size = cluster_size
        return wh

    def test_pro_2xsmall(self):
        wh = self._make_wh("PRO", "2X-Small")
        assert _match_warehouse_to_engine(wh) == "databricks-serverless-2xs"

    def test_pro_xsmall(self):
        wh = self._make_wh("PRO", "X-Small")
        assert _match_warehouse_to_engine(wh) == "databricks-serverless-xs"

    def test_pro_small(self):
        wh = self._make_wh("PRO", "Small")
        assert _match_warehouse_to_engine(wh) == "databricks-serverless-s"

    def test_pro_unknown_size_returns_none(self):
        """Unrecognized cluster size → no match."""
        wh = self._make_wh("PRO", "4X-Large")
        assert _match_warehouse_to_engine(wh) is None

    def test_classic_type_returns_none(self):
        """Non-PRO warehouse types are not matched."""
        wh = self._make_wh("CLASSIC", "Small")
        assert _match_warehouse_to_engine(wh) is None

    def test_none_warehouse_type(self):
        """Warehouse with no type set → None."""
        wh = MagicMock()
        wh.warehouse_type = None
        wh.cluster_size = "Small"
        assert _match_warehouse_to_engine(wh) is None

    def test_none_cluster_size(self):
        """PRO warehouse with no cluster size → None."""
        wh = self._make_wh("PRO", None)
        # cluster_size=None → _CLUSTER_SIZE_TO_ENGINE.get(None) = None
        assert _match_warehouse_to_engine(wh) is None


# ---------------------------------------------------------------------------
# _load_profile_config
# ---------------------------------------------------------------------------


class TestLoadProfileConfig:
    """Tests for loading routing profile config from DB."""

    @patch("main.db")
    def test_loads_specific_profile(self, mock_db):
        config = {"routingMode": "smart", "routingPriority": 0.5}
        mock_db.fetch_one.return_value = {"config": config}
        result = _load_profile_config(42)
        mock_db.fetch_one.assert_called_once_with(
            "SELECT config FROM routing_profiles WHERE id = %s", (42,)
        )
        assert result == config

    @patch("main.db")
    def test_profile_not_found_raises_404(self, mock_db):
        mock_db.fetch_one.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _load_profile_config(999)
        assert exc_info.value.status_code == 404
        assert "999" in exc_info.value.detail

    @patch("main.db")
    def test_loads_default_profile_when_no_id(self, mock_db):
        config = {"routingMode": "single", "singleEngineId": "duckdb-2gb"}
        mock_db.fetch_one.return_value = {"config": config}
        result = _load_profile_config(None)
        mock_db.fetch_one.assert_called_once_with(
            "SELECT config FROM routing_profiles WHERE is_default = true"
        )
        assert result == config

    @patch("main.db")
    def test_no_default_profile_returns_none(self, mock_db):
        mock_db.fetch_one.return_value = None
        result = _load_profile_config(None)
        assert result is None

    @patch("main.db")
    def test_non_dict_config_returns_empty_dict(self, mock_db):
        """If config column is somehow not a dict (e.g., JSON parse issue), return {}."""
        mock_db.fetch_one.return_value = {"config": "not a dict"}
        result = _load_profile_config(42)
        assert result == {}


# ---------------------------------------------------------------------------
# _profile_config_to_routing_params
# ---------------------------------------------------------------------------


class TestProfileConfigToRoutingParams:
    """Tests for converting profile config to (routing_mode, RoutingSettings)."""

    def test_smart_mode_balanced(self):
        config = {"routingMode": "smart", "routingPriority": 0.5}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings is not None
        assert settings.fit_weight == 0.5
        assert settings.cost_weight == 0.5

    def test_smart_mode_cost_optimized(self):
        """routingPriority=0 → cost-optimized (fit_weight=0, cost_weight=1)."""
        config = {"routingMode": "smart", "routingPriority": 0}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings.fit_weight == 0.0
        assert settings.cost_weight == 1.0

    def test_smart_mode_performance_optimized(self):
        """routingPriority=1 → performance-optimized (fit_weight=1, cost_weight=0)."""
        config = {"routingMode": "smart", "routingPriority": 1}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings.fit_weight == 1.0
        assert settings.cost_weight == 0.0

    @patch("main.db")
    def test_single_mode_duckdb_engine(self, mock_db):
        """Single mode with a DuckDB engine → forced 'duckdb'."""
        mock_db.fetch_one.return_value = {"engine_type": "duckdb"}
        config = {"routingMode": "single", "singleEngineId": "duckdb-2gb-2cpu"}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "duckdb"
        assert settings is None

    @patch("main.db")
    def test_single_mode_databricks_engine(self, mock_db):
        """Single mode with a Databricks engine → forced 'databricks'."""
        mock_db.fetch_one.return_value = {"engine_type": "databricks_sql"}
        config = {
            "routingMode": "single",
            "singleEngineId": "databricks-serverless-2xs",
        }
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "databricks"
        assert settings is None

    @patch("main.db")
    def test_single_mode_unknown_engine_falls_back_to_smart(self, mock_db):
        """Single mode with an engine not found in DB → fallback to smart."""
        mock_db.fetch_one.return_value = None
        config = {"routingMode": "single", "singleEngineId": "nonexistent"}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings is None

    @patch("main.db")
    def test_single_mode_no_engine_id_falls_back_to_smart(self, mock_db):
        """Single mode without singleEngineId → fallback to smart."""
        config = {"routingMode": "single"}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings is None
        # db.fetch_one should NOT be called since there's no engine_id
        mock_db.fetch_one.assert_not_called()

    def test_missing_routing_mode_defaults_to_smart(self):
        """Empty config → defaults to smart mode."""
        config = {}
        mode, settings = _profile_config_to_routing_params(config)
        assert mode == "smart"
        assert settings is not None
        # Default routingPriority is 0.5
        assert settings.fit_weight == 0.5

    def test_missing_routing_priority_defaults_to_balanced(self):
        config = {"routingMode": "smart"}
        mode, settings = _profile_config_to_routing_params(config)
        assert settings.fit_weight == 0.5
        assert settings.cost_weight == 0.5


# ---------------------------------------------------------------------------
# _databricks_error_to_http
# ---------------------------------------------------------------------------


class TestDatabricksErrorToHttp:
    """Tests for translating Databricks SDK exceptions to HTTPException."""

    def test_unauthenticated_maps_to_401(self):
        from databricks.sdk.errors import Unauthenticated

        exc = _databricks_error_to_http(Unauthenticated("bad token"))
        assert exc.status_code == 401

    def test_permission_denied_maps_to_403(self):
        from databricks.sdk.errors import PermissionDenied

        exc = _databricks_error_to_http(PermissionDenied("no access"))
        assert exc.status_code == 403

    def test_not_found_maps_to_404(self):
        from databricks.sdk.errors import NotFound

        exc = _databricks_error_to_http(NotFound("no such table"))
        assert exc.status_code == 404

    def test_too_many_requests_maps_to_429(self):
        from databricks.sdk.errors import TooManyRequests

        exc = _databricks_error_to_http(TooManyRequests("slow down"))
        assert exc.status_code == 429

    def test_temporarily_unavailable_maps_to_503(self):
        from databricks.sdk.errors import TemporarilyUnavailable

        exc = _databricks_error_to_http(TemporarilyUnavailable("try later"))
        assert exc.status_code == 503

    def test_deadline_exceeded_maps_to_504(self):
        from databricks.sdk.errors import DeadlineExceeded

        exc = _databricks_error_to_http(DeadlineExceeded("timeout"))
        assert exc.status_code == 504

    def test_unknown_exception_maps_to_500(self):
        exc = _databricks_error_to_http(RuntimeError("something weird"))
        assert exc.status_code == 500
        assert "RuntimeError" in exc.detail

    def test_connection_error_maps_to_502(self):
        import requests

        exc = _databricks_error_to_http(requests.ConnectionError("refused"))
        assert exc.status_code == 502
        assert "reach Databricks" in exc.detail

    def test_timeout_error_maps_to_504(self):
        import requests

        exc = _databricks_error_to_http(requests.Timeout("timed out"))
        assert exc.status_code == 504
