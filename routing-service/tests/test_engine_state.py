"""Tests for engine_state module."""

import time
from unittest.mock import patch, MagicMock

import engine_state


class TestGetEngineState:
    def setup_method(self):
        engine_state._engine_states.clear()

    def test_unknown_when_not_tracked(self):
        assert engine_state.get_engine_state("nonexistent") == "unknown"

    def test_returns_tracked_state(self):
        engine_state._engine_states["duckdb-1"] = "running"
        assert engine_state.get_engine_state("duckdb-1") == "running"

    def test_get_engine_states_returns_copy(self):
        engine_state._engine_states["duckdb-1"] = "running"
        states = engine_state.get_engine_states()
        states["duckdb-1"] = "stopped"
        # Original should be unchanged
        assert engine_state._engine_states["duckdb-1"] == "running"


class TestPollAllEngines:
    def setup_method(self):
        engine_state._engine_states.clear()
        engine_state._get_workspace_client = None

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.httpx.get")
    @patch("engine_state.db.fetch_all")
    def test_duckdb_health_probe_running(self, mock_fetch, mock_httpx_get, _mock_profile):
        """DuckDB engines with a reachable health endpoint are marked 'running'."""
        mock_fetch.return_value = [
            {
                "id": "duckdb-1",
                "engine_type": "duckdb",
                "config": {},
                "k8s_service_name": "duckdb-worker-small",
            },
            {
                "id": "duckdb-2",
                "engine_type": "duckdb",
                "config": {},
                "k8s_service_name": "duckdb-worker-medium",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_httpx_get.return_value = mock_resp

        engine_state._poll_all_engines()
        assert engine_state._engine_states["duckdb-1"] == "running"
        assert engine_state._engine_states["duckdb-2"] == "running"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.httpx.get", side_effect=Exception("connection refused"))
    @patch("engine_state.db.fetch_all")
    def test_duckdb_health_probe_stopped(self, mock_fetch, mock_httpx_get, _mock_profile):
        """DuckDB engines with unreachable health endpoint are marked 'stopped'."""
        mock_fetch.return_value = [
            {
                "id": "duckdb-1",
                "engine_type": "duckdb",
                "config": {},
                "k8s_service_name": "duckdb-worker-small",
            },
        ]
        engine_state._poll_all_engines()
        assert engine_state._engine_states["duckdb-1"] == "stopped"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_duckdb_no_service_name_unknown(self, mock_fetch, _mock_profile):
        """DuckDB engines without k8s_service_name are marked 'unknown'."""
        mock_fetch.return_value = [
            {
                "id": "duckdb-1",
                "engine_type": "duckdb",
                "config": {},
                "k8s_service_name": None,
            },
        ]
        engine_state._poll_all_engines()
        assert engine_state._engine_states["duckdb-1"] == "unknown"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_databricks_no_client_unknown(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {
                "id": "db-1",
                "engine_type": "databricks_sql",
                "config": {"warehouse_id": "abc"},
            },
        ]
        engine_state._get_workspace_client = None
        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "unknown"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_databricks_running(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {
                "id": "db-1",
                "engine_type": "databricks_sql",
                "config": {"warehouse_id": "abc"},
            },
        ]
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "RUNNING"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "running"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_databricks_stopped(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {
                "id": "db-1",
                "engine_type": "databricks_sql",
                "config": {"warehouse_id": "abc"},
            },
        ]
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "STOPPED"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "stopped"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_databricks_starting(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {
                "id": "db-1",
                "engine_type": "databricks_sql",
                "config": {"warehouse_id": "abc"},
            },
        ]
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "STARTING"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "starting"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_databricks_api_error_unknown(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {
                "id": "db-1",
                "engine_type": "databricks_sql",
                "config": {"warehouse_id": "abc"},
            },
        ]
        mock_wc = MagicMock()
        mock_wc.warehouses.get.side_effect = RuntimeError("connection error")
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "unknown"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_db_fetch_error_no_crash(self, mock_fetch, _mock_profile):
        mock_fetch.side_effect = RuntimeError("DB down")
        # Should not raise — just logs and returns
        engine_state._poll_all_engines()

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_unknown_engine_type(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {"id": "x-1", "engine_type": "spark_cluster", "config": {}},
        ]
        engine_state._poll_all_engines()
        assert engine_state._engine_states["x-1"] == "unknown"

    @patch("engine_state.db.fetch_one", return_value=None)
    @patch("engine_state.db.fetch_all")
    def test_no_warehouse_id_unknown(self, mock_fetch, _mock_profile):
        mock_fetch.return_value = [
            {"id": "db-1", "engine_type": "databricks_sql", "config": {}},
        ]
        mock_wc = MagicMock()
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "unknown"


class TestPollingLifecycle:
    def setup_method(self):
        engine_state._engine_states.clear()
        engine_state.stop_polling()

    def teardown_method(self):
        engine_state.stop_polling()

    @patch("engine_state.db.fetch_all", return_value=[])
    def test_start_and_stop(self, mock_fetch):
        engine_state.start_polling(interval_seconds=60)
        assert engine_state._poll_thread is not None
        assert engine_state._poll_thread.is_alive()

        engine_state.stop_polling()
        # Thread should terminate
        time.sleep(0.1)
        assert engine_state._poll_thread is None

    @patch("engine_state.db.fetch_all", return_value=[])
    def test_double_start_no_error(self, mock_fetch):
        engine_state.start_polling(interval_seconds=60)
        engine_state.start_polling(interval_seconds=60)  # should warn but not crash
        engine_state.stop_polling()


class TestWarehouseMappingFromProfile:
    """Tests that serverless Databricks engines get warehouse_id from routing profile."""

    def setup_method(self):
        engine_state._engine_states.clear()

    @patch("engine_state.db.fetch_one")
    @patch("engine_state.db.fetch_all")
    def test_serverless_engine_uses_profile_mapping(self, mock_fetch_all, mock_fetch_one):
        """Engine with no config.warehouse_id resolves from warehouseMappings."""
        mock_fetch_all.return_value = [
            {"id": "databricks-serverless-2xs", "engine_type": "databricks_sql", "config": {}},
        ]
        mock_fetch_one.return_value = {
            "config": {
                "warehouseMappings": [
                    {"engineId": "databricks-serverless-2xs", "warehouseId": "abc123"},
                ]
            }
        }
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "RUNNING"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["databricks-serverless-2xs"] == "running"
        mock_wc.warehouses.get.assert_called_once_with("abc123")

    @patch("engine_state.db.fetch_one")
    @patch("engine_state.db.fetch_all")
    def test_config_warehouse_id_takes_precedence(self, mock_fetch_all, mock_fetch_one):
        """config.warehouse_id is preferred over profile mapping."""
        mock_fetch_all.return_value = [
            {"id": "db-1", "engine_type": "databricks_sql", "config": {"warehouse_id": "from-config"}},
        ]
        mock_fetch_one.return_value = {
            "config": {
                "warehouseMappings": [
                    {"engineId": "db-1", "warehouseId": "from-profile"},
                ]
            }
        }
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "RUNNING"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        mock_wc.warehouses.get.assert_called_once_with("from-config")

    @patch("engine_state.db.fetch_one")
    @patch("engine_state.db.fetch_all")
    def test_no_profile_no_config_still_unknown(self, mock_fetch_all, mock_fetch_one):
        """Engine with no warehouse_id anywhere stays unknown."""
        mock_fetch_all.return_value = [
            {"id": "db-1", "engine_type": "databricks_sql", "config": {}},
        ]
        mock_fetch_one.return_value = None
        mock_wc = MagicMock()
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "unknown"

    @patch("engine_state.db.fetch_one", side_effect=RuntimeError("DB error"))
    @patch("engine_state.db.fetch_all")
    def test_profile_fetch_error_graceful(self, mock_fetch_all, mock_fetch_one):
        """Profile fetch failure doesn't crash polling — falls back to config."""
        mock_fetch_all.return_value = [
            {"id": "db-1", "engine_type": "databricks_sql", "config": {"warehouse_id": "abc"}},
        ]
        mock_wc = MagicMock()
        mock_warehouse = MagicMock()
        mock_warehouse.state.value = "RUNNING"
        mock_wc.warehouses.get.return_value = mock_warehouse
        engine_state._get_workspace_client = lambda: mock_wc

        engine_state._poll_all_engines()
        assert engine_state._engine_states["db-1"] == "running"
