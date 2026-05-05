"""Tests for idle_timer module."""

import time
from unittest.mock import patch, MagicMock

import idle_timer


class TestRecordQuery:
    def setup_method(self):
        idle_timer._last_query_time.clear()

    def test_record_query_stores_timestamp(self):
        idle_timer.record_query("duckdb-xsmall")
        assert "duckdb-xsmall" in idle_timer._last_query_time
        assert abs(idle_timer._last_query_time["duckdb-xsmall"] - time.time()) < 1

    def test_record_query_updates_timestamp(self):
        idle_timer._last_query_time["duckdb-xsmall"] = 100.0
        idle_timer.record_query("duckdb-xsmall")
        assert idle_timer._last_query_time["duckdb-xsmall"] > 100.0


class TestCheckIdleEngines:
    def setup_method(self):
        idle_timer._last_query_time.clear()

    @patch("idle_timer.engines_api._scale_deployment")
    @patch("idle_timer.db.fetch_all")
    def test_scales_down_idle_engine(self, mock_fetch, mock_scale):
        mock_fetch.return_value = [
            {"id": "duckdb-small", "k8s_service_name": "duckdb-worker-small", "idle_timeout_minutes": 1}
        ]
        # Last query was 120 seconds ago (timeout is 60s)
        idle_timer._last_query_time["duckdb-small"] = time.time() - 120

        idle_timer._check_idle_engines()

        mock_scale.assert_called_once_with("duckdb-worker-small", 0)
        assert "duckdb-small" not in idle_timer._last_query_time

    @patch("idle_timer.engines_api._scale_deployment")
    @patch("idle_timer.db.fetch_all")
    def test_does_not_scale_active_engine(self, mock_fetch, mock_scale):
        mock_fetch.return_value = [
            {"id": "duckdb-small", "k8s_service_name": "duckdb-worker-small", "idle_timeout_minutes": 15}
        ]
        # Last query was 10 seconds ago (timeout is 900s)
        idle_timer._last_query_time["duckdb-small"] = time.time() - 10

        idle_timer._check_idle_engines()

        mock_scale.assert_not_called()

    @patch("idle_timer.engines_api._scale_deployment")
    @patch("idle_timer.db.fetch_all")
    def test_skips_engine_never_queried(self, mock_fetch, mock_scale):
        mock_fetch.return_value = [
            {"id": "duckdb-medium", "k8s_service_name": "duckdb-worker-medium", "idle_timeout_minutes": 15}
        ]
        # No entry in _last_query_time

        idle_timer._check_idle_engines()

        mock_scale.assert_not_called()
