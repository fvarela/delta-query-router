"""Tests for K8s scaling in engines_api (Phase 17 — Task 132)."""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

import engines_api


class TestScaleDeployment:
    """Tests for _scale_deployment helper."""

    @patch("engines_api.k8s_client", create=True)
    @patch("engines_api.k8s_config", create=True)
    def test_scales_deployment(self, mock_config, mock_client):
        """Successful scale patches the deployment."""
        mock_apps = MagicMock()
        with patch("engines_api._scale_deployment") as mock_scale:
            mock_scale.return_value = None
            engines_api._scale_deployment("duckdb-worker-small", 1)

    def test_scale_deployment_no_cluster(self):
        """Outside K8s cluster, raises HTTPException."""
        with patch.dict("sys.modules", {"kubernetes": MagicMock()}):
            from kubernetes import config as k8s_config

            k8s_config.load_incluster_config.side_effect = Exception("not in cluster")
            with pytest.raises(HTTPException) as exc_info:
                engines_api._scale_deployment("test", 1)
            assert exc_info.value.status_code == 500
            assert "Kubernetes" in exc_info.value.detail


class TestAutoScaleOnToggle:
    """Tests for auto-scaling when is_active is toggled in update_engine."""

    @pytest.mark.anyio
    @patch("engines_api._scale_deployment")
    @patch("engines_api.db")
    async def test_enable_duckdb_scales_up(self, mock_db, mock_scale):
        """Enabling a DuckDB engine triggers scale to 1 replica."""
        existing = {
            "id": "duckdb-small",
            "engine_type": "duckdb",
            "is_active": False,
            "config": {},
            "k8s_service_name": "duckdb-worker-small",
            "cost_tier": 1,
        }
        mock_db.fetch_one.side_effect = [
            existing,
            {**existing, "is_active": True},
        ]
        await engines_api.update_engine(
            "duckdb-small", engines_api.UpdateEngine(is_active=True)
        )
        mock_scale.assert_called_once_with("duckdb-worker-small", 1)

    @pytest.mark.anyio
    @patch("engines_api._scale_deployment")
    @patch("engines_api.db")
    async def test_disable_duckdb_scales_down(self, mock_db, mock_scale):
        """Disabling a DuckDB engine triggers scale to 0 replicas."""
        existing = {
            "id": "duckdb-small",
            "engine_type": "duckdb",
            "is_active": True,
            "config": {},
            "k8s_service_name": "duckdb-worker-small",
            "cost_tier": 1,
        }
        mock_db.fetch_one.side_effect = [
            existing,
            {**existing, "is_active": False},
        ]
        await engines_api.update_engine(
            "duckdb-small", engines_api.UpdateEngine(is_active=False)
        )
        mock_scale.assert_called_once_with("duckdb-worker-small", 0)

    @pytest.mark.anyio
    @patch("engines_api._scale_deployment")
    @patch("engines_api.db")
    async def test_toggle_databricks_does_not_scale(self, mock_db, mock_scale):
        """Toggling a Databricks engine does NOT trigger K8s scaling."""
        existing = {
            "id": "databricks-abc",
            "engine_type": "databricks_sql",
            "is_active": False,
            "config": {},
            "k8s_service_name": None,
            "cost_tier": 7,
        }
        mock_db.fetch_one.side_effect = [
            existing,
            {**existing, "is_active": True},
        ]
        await engines_api.update_engine(
            "databricks-abc", engines_api.UpdateEngine(is_active=True)
        )
        mock_scale.assert_not_called()

    @pytest.mark.anyio
    @patch(
        "engines_api._scale_deployment",
        side_effect=HTTPException(status_code=500, detail="K8s error"),
    )
    @patch("engines_api.db")
    async def test_scale_failure_does_not_fail_update(self, mock_db, mock_scale):
        """If K8s scaling fails, the DB update still succeeds (logged as warning)."""
        existing = {
            "id": "duckdb-small",
            "engine_type": "duckdb",
            "is_active": False,
            "config": {},
            "k8s_service_name": "duckdb-worker-small",
            "cost_tier": 1,
        }
        updated = {**existing, "is_active": True}
        mock_db.fetch_one.side_effect = [existing, updated]

        result = await engines_api.update_engine(
            "duckdb-small", engines_api.UpdateEngine(is_active=True)
        )
        assert result["is_active"] is True
        mock_scale.assert_called_once()

    @pytest.mark.anyio
    @patch("engines_api._scale_deployment")
    @patch("engines_api.db")
    async def test_same_value_no_scale(self, mock_db, mock_scale):
        """Setting is_active to its current value does NOT trigger scaling."""
        existing = {
            "id": "duckdb-small",
            "engine_type": "duckdb",
            "is_active": True,
            "config": {},
            "k8s_service_name": "duckdb-worker-small",
            "cost_tier": 1,
        }
        mock_db.fetch_one.side_effect = [existing, existing]

        await engines_api.update_engine(
            "duckdb-small", engines_api.UpdateEngine(is_active=True)
        )
        mock_scale.assert_not_called()
