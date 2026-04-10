"""Tests for log_cleaner module (Phase 17)."""

from unittest.mock import patch, MagicMock

import pytest

import log_cleaner


class TestGetSettings:
    """Tests for log_cleaner.get_settings()."""

    @patch("log_cleaner.db.fetch_one")
    def test_returns_db_values(self, mock_fetch):
        mock_fetch.return_value = {"retention_days": 14, "max_size_mb": 512}
        result = log_cleaner.get_settings()
        assert result == {"retention_days": 14, "max_size_mb": 512}

    @patch("log_cleaner.db.fetch_one")
    def test_returns_defaults_when_no_row(self, mock_fetch):
        mock_fetch.return_value = None
        result = log_cleaner.get_settings()
        assert result == {"retention_days": 30, "max_size_mb": 1024}


class TestUpdateSettings:
    """Tests for log_cleaner.update_settings()."""

    @patch("log_cleaner.db.fetch_one")
    def test_update_retention_days(self, mock_fetch):
        mock_fetch.return_value = {"retention_days": 7, "max_size_mb": 1024}
        result = log_cleaner.update_settings(retention_days=7)
        assert result["retention_days"] == 7
        call_args = mock_fetch.call_args
        assert "retention_days" in call_args[0][0]

    @patch("log_cleaner.db.fetch_one")
    def test_update_max_size_mb(self, mock_fetch):
        mock_fetch.return_value = {"retention_days": 30, "max_size_mb": 2048}
        result = log_cleaner.update_settings(max_size_mb=2048)
        assert result["max_size_mb"] == 2048

    @patch("log_cleaner.db.fetch_one")
    def test_update_both(self, mock_fetch):
        mock_fetch.return_value = {"retention_days": 7, "max_size_mb": 256}
        result = log_cleaner.update_settings(retention_days=7, max_size_mb=256)
        assert result == {"retention_days": 7, "max_size_mb": 256}

    def test_retention_days_must_be_positive(self):
        with pytest.raises(ValueError, match="retention_days must be >= 1"):
            log_cleaner.update_settings(retention_days=0)

    def test_max_size_mb_must_be_positive(self):
        with pytest.raises(ValueError, match="max_size_mb must be >= 1"):
            log_cleaner.update_settings(max_size_mb=0)

    @patch("log_cleaner.db.fetch_one")
    def test_no_fields_returns_current(self, mock_fetch):
        """Calling update_settings() with no args returns current settings."""
        mock_fetch.return_value = {"retention_days": 30, "max_size_mb": 1024}
        result = log_cleaner.update_settings()
        assert result == {"retention_days": 30, "max_size_mb": 1024}


class TestPurgeOldLogs:
    """Tests for log_cleaner._purge_old_logs()."""

    @patch("log_cleaner.db.fetch_all")
    @patch("log_cleaner.db.execute")
    def test_purge_deletes_old_logs(self, mock_exec, mock_fetch_all):
        mock_fetch_all.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = log_cleaner._purge_old_logs(30)
        assert result == 3
        # Should have called execute for routing_decisions first
        assert mock_exec.call_count == 1
        assert "routing_decisions" in mock_exec.call_args[0][0]
        # Then fetch_all for query_logs
        assert "query_logs" in mock_fetch_all.call_args[0][0]

    @patch("log_cleaner.db.fetch_all")
    @patch("log_cleaner.db.execute")
    def test_purge_no_old_logs(self, mock_exec, mock_fetch_all):
        mock_fetch_all.return_value = []
        result = log_cleaner._purge_old_logs(30)
        assert result == 0

    @patch("log_cleaner.db.fetch_all")
    @patch("log_cleaner.db.execute")
    def test_purge_none_result(self, mock_exec, mock_fetch_all):
        mock_fetch_all.return_value = None
        result = log_cleaner._purge_old_logs(30)
        assert result == 0


class TestPurgeNow:
    """Tests for log_cleaner.purge_now()."""

    @patch("log_cleaner._purge_old_logs", return_value=5)
    @patch(
        "log_cleaner.get_settings",
        return_value={"retention_days": 14, "max_size_mb": 1024},
    )
    def test_uses_settings_retention_days(self, mock_settings, mock_purge):
        result = log_cleaner.purge_now()
        assert result == 5
        mock_purge.assert_called_once_with(14)


class TestLifecycle:
    """Tests for start/stop background thread."""

    def setup_method(self):
        log_cleaner.stop()

    def teardown_method(self):
        log_cleaner.stop()

    @patch("log_cleaner._run_purge")
    def test_start_creates_thread(self, mock_purge):
        log_cleaner.start(interval_seconds=3600)
        assert log_cleaner._thread is not None
        assert log_cleaner._thread.is_alive()

    @patch("log_cleaner._run_purge")
    def test_stop_terminates_thread(self, mock_purge):
        log_cleaner.start(interval_seconds=3600)
        log_cleaner.stop()
        assert log_cleaner._thread is None

    @patch("log_cleaner._run_purge")
    def test_double_start_is_safe(self, mock_purge):
        log_cleaner.start(interval_seconds=3600)
        thread1 = log_cleaner._thread
        log_cleaner.start(interval_seconds=3600)
        # Should be the same thread (second start is a no-op)
        assert log_cleaner._thread is thread1
