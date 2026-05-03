"""Unit tests for cold_start_measure.py."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def patch_db():
    with patch("cold_start_measure.db") as mock:
        yield mock


class TestGetDummyTable:
    def test_returns_table_name(self, patch_db):
        import cold_start_measure
        patch_db.fetch_one.return_value = {"table_name": "cat.sch.t1"}
        assert cold_start_measure._get_dummy_table() == "cat.sch.t1"

    def test_raises_when_no_collections(self, patch_db):
        import cold_start_measure
        patch_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="No collections"):
            cold_start_measure._get_dummy_table()


class TestMeasureDuckDB:
    def test_always_returns_zero(self, patch_db):
        """DuckDB is always-on — no cold start. Returns 0ms without network calls."""
        import cold_start_measure

        engine = {"id": "duckdb-1", "engine_type": "duckdb", "k8s_service_name": "duckdb"}
        result = cold_start_measure._measure_duckdb(engine, "cat.sch.t", "h", "t")
        assert result == 0.0


class TestMeasureDatabricks:
    @patch("cold_start_measure.ephemeral_warehouses")
    @patch("cold_start_measure.time.sleep")
    @patch("cold_start_measure.time.monotonic")
    @patch("cold_start_measure.time.perf_counter")
    def test_full_lifecycle(self, mock_perf, mock_mono, mock_sleep, mock_eph, patch_db):
        import cold_start_measure

        mock_eph.create_for_benchmark.return_value = "wh-1"
        mock_eph.wait_for_running.return_value = True

        mock_ws = MagicMock()
        # _wait_for_stopped
        stopped_wh = MagicMock()
        stopped_wh.state.value = "STOPPED"
        mock_ws.warehouses.get.return_value = stopped_wh
        mock_mono.side_effect = [0.0, 0.1, 1.0, 1.1]  # _wait_for_stopped + poll loop

        # Statement execution — patch the import inside the function
        mock_sql = MagicMock()
        with patch.dict("sys.modules", {"databricks.sdk.service.sql": mock_sql}):
            # execute_statement returns async PENDING
            mock_submit = MagicMock()
            mock_submit.statement_id = "stmt-1"
            mock_submit.status.state = mock_sql.StatementState.PENDING
            mock_ws.statement_execution.execute_statement.return_value = mock_submit

            # get_statement returns SUCCEEDED on first poll
            mock_result = MagicMock()
            mock_result.status.state = mock_sql.StatementState.SUCCEEDED
            mock_ws.statement_execution.get_statement.return_value = mock_result

            # Wall-clock: submit at t=0, poll completes at t=10 → 10000ms cold start
            mock_perf.side_effect = [0.0, 10.0]

            engine = {"id": "db-xs", "engine_type": "databricks_sql", "config": {"cluster_size": "2X-Small"}}
            result = cold_start_measure._measure_databricks(engine, "cat.sch.t", mock_ws)

        assert result == pytest.approx(10000.0)
        mock_eph.delete_warehouse.assert_called_once_with(mock_ws, "wh-1")
        mock_ws.warehouses.stop.assert_called_once_with("wh-1")
        # No explicit start call — warehouse auto-starts from the query
        mock_ws.warehouses.start.assert_not_called()

    @patch("cold_start_measure.ephemeral_warehouses")
    def test_cleanup_on_failure(self, mock_eph, patch_db):
        import cold_start_measure

        mock_eph.create_for_benchmark.return_value = "wh-2"
        mock_eph.wait_for_running.return_value = False

        mock_ws = MagicMock()
        engine = {"id": "db-xs", "engine_type": "databricks_sql", "config": {"cluster_size": "X-Small"}}

        with pytest.raises(RuntimeError, match="failed to reach RUNNING"):
            cold_start_measure._measure_databricks(engine, "cat.sch.t", mock_ws)

        mock_eph.delete_warehouse.assert_called_once_with(mock_ws, "wh-2")


class TestMeasureColdStart:
    def test_engine_not_found(self, patch_db):
        import cold_start_measure
        patch_db.fetch_one.return_value = None
        with pytest.raises(ValueError, match="Engine not found"):
            cold_start_measure.measure_cold_start("nonexistent")

    @patch("cold_start_measure._measure_duckdb", return_value=0.0)
    @patch("cold_start_measure._get_dummy_table", return_value="cat.sch.t")
    def test_duckdb_stores_result(self, mock_table, mock_measure, patch_db):
        import cold_start_measure

        patch_db.fetch_one.return_value = {
            "id": "duckdb-1", "engine_type": "duckdb", "config": "{}",
            "k8s_service_name": "duckdb-worker-small",
        }

        result = cold_start_measure.measure_cold_start("duckdb-1")

        assert result == 0.0
        patch_db.execute.assert_called_once()
        args = patch_db.execute.call_args[0]
        assert "INSERT INTO engine_cold_starts" in args[0]
        assert args[1] == ("duckdb-1", 0.0)

    @patch("cold_start_measure._get_workspace_client", return_value=MagicMock())
    @patch("cold_start_measure._measure_databricks", return_value=3500.0)
    @patch("cold_start_measure._get_dummy_table", return_value="cat.sch.t")
    def test_databricks_stores_result(self, mock_table, mock_measure, mock_ws, patch_db):
        import cold_start_measure

        patch_db.fetch_one.return_value = {
            "id": "db-xs", "engine_type": "databricks_sql", "config": "{}",
        }

        result = cold_start_measure.measure_cold_start("db-xs")

        assert result == 3500.0
        patch_db.execute.assert_called_once()

    @patch("cold_start_measure._get_dummy_table", return_value="cat.sch.t")
    def test_duckdb_no_credentials_still_works(self, mock_table, patch_db):
        """DuckDB doesn't need credentials — always returns 0ms."""
        import cold_start_measure

        patch_db.fetch_one.return_value = {
            "id": "duckdb-1", "engine_type": "duckdb", "config": "{}",
            "k8s_service_name": "duckdb-worker-small",
        }

        result = cold_start_measure.measure_cold_start("duckdb-1")
        assert result == 0.0
