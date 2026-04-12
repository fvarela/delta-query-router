"""Tests for tpcds_api.py — TPC-DS creation, status, listing, deletion endpoints."""

import time
from unittest.mock import patch, MagicMock, call

import pytest
from fastapi.testclient import TestClient

import auth
import main as _main_module
import tpcds_api
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_header():
    token = "admin-tok-tpcds"
    auth._active_tokens[token] = "admin"
    return {"Authorization": f"Bearer {token}"}


def _user_header():
    """Non-admin user."""
    token = "user-tok-tpcds"
    session = auth.UserSession(
        username="regularuser",
        email="user@example.com",
        databricks_host="https://ws.databricks.com",
        pat="dapi_user_pat",
        workspace_client=MagicMock(),
        created_at=time.time(),
        expires_at=time.time() + 3600,
    )
    auth._user_sessions[token] = session
    return {"Authorization": f"Bearer {token}"}


def _mock_me(user_name="admin@company.com"):
    me = MagicMock()
    me.user_name = user_name
    return me


def _mock_statement_success():
    from databricks.sdk.service.sql import StatementState

    resp = MagicMock()
    resp.status.state = StatementState.SUCCEEDED
    return resp


def _mock_statement_failure(msg="SQL error"):
    from databricks.sdk.service.sql import StatementState

    resp = MagicMock()
    resp.status.state = StatementState.FAILED
    resp.status.error.message = msg
    return resp


def _tpcds_row(
    id=1,
    catalog_name="test_tpcds",
    schema_name="sf1",
    scale_factor=1,
    status="creating",
    job_run_id=None,
    error_message=None,
    tables_created=0,
    total_tables=25,
):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return {
        "id": id,
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "scale_factor": scale_factor,
        "status": status,
        "job_run_id": job_run_id,
        "error_message": error_message,
        "tables_created": tables_created,
        "total_tables": total_tables,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# check_samples_available  (T94)
# ---------------------------------------------------------------------------


class TestCheckSamplesAvailable:
    def test_samples_available(self):
        wc = MagicMock()
        wc.catalogs.get.return_value = MagicMock()
        wc.schemas.get.return_value = MagicMock()
        assert tpcds_api.check_samples_available(wc) is True

    def test_no_samples_catalog(self):
        wc = MagicMock()
        wc.catalogs.get.side_effect = Exception("Not found")
        assert tpcds_api.check_samples_available(wc) is False

    def test_no_tpcds_sf1_schema(self):
        wc = MagicMock()
        wc.catalogs.get.return_value = MagicMock()
        wc.schemas.get.side_effect = Exception("Not found")
        assert tpcds_api.check_samples_available(wc) is False


# ---------------------------------------------------------------------------
# GET /api/tpcds/preflight  (T94)
# ---------------------------------------------------------------------------


class TestPreflight:
    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    def test_all_green(self, mock_wc):
        mock_summary = MagicMock()
        mock_summary.external_access_enabled = True
        mock_wc.metastores.summary.return_value = mock_summary
        mock_wc.catalogs.get.return_value = MagicMock()
        mock_wc.schemas.get.return_value = MagicMock()
        resp = client.get("/api/tpcds/preflight", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["samples_available"] is True
        assert data["metastore_external_access"] is True
        assert data["warehouse_configured"] is True

    @patch("main._warehouse_id", None)
    @patch("main._workspace_client")
    def test_no_warehouse(self, mock_wc):
        mock_summary = MagicMock()
        mock_summary.external_access_enabled = False
        mock_wc.metastores.summary.return_value = mock_summary
        mock_wc.catalogs.get.side_effect = Exception("nope")
        resp = client.get("/api/tpcds/preflight", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["warehouse_configured"] is False
        assert data["metastore_external_access"] is False
        assert data["samples_available"] is False

    def test_403_for_non_admin(self):
        resp = client.get("/api/tpcds/preflight", headers=_user_header())
        assert resp.status_code == 403

    def test_503_when_not_configured(self):
        with patch("main._workspace_client", None):
            resp = client.get("/api/tpcds/preflight", headers=_admin_header())
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/tpcds/create  (T90 SF1, T91 SF10/SF100)
# ---------------------------------------------------------------------------


class TestCreateTpcds:
    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api.check_samples_available", return_value=True)
    @patch("tpcds_api.threading.Thread")
    def test_sf1_ctas_path(self, mock_thread, mock_samples, mock_db, mock_wc):
        mock_db.fetch_one.side_effect = [
            None,  # duplicate check
            _tpcds_row(id=1, status="creating"),  # insert
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "test_tpcds",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "ctas"
        assert data["status"] == "creating"
        assert data["catalog_name"] == "test_tpcds"
        # Background thread should be started
        mock_thread.return_value.start.assert_called_once()

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api.check_samples_available", return_value=False)
    @patch("tpcds_api._submit_dsdgen_job", return_value="12345")
    def test_sf1_job_fallback(self, mock_submit, mock_samples, mock_db, mock_wc):
        """When samples not available, SF1 falls back to Job path."""
        mock_db.fetch_one.side_effect = [
            None,  # duplicate check
            _tpcds_row(id=2, status="creating"),  # insert
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "test_tpcds_fb",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "job"
        assert data["job_run_id"] == "12345"

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api._submit_dsdgen_job", return_value="67890")
    def test_sf10_job_path(self, mock_submit, mock_db, mock_wc):
        mock_db.fetch_one.side_effect = [
            None,  # duplicate check
            _tpcds_row(id=3, scale_factor=10),  # insert
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "tpcds_sf10",
                "schema_name": "sf10",
                "scale_factor": 10,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "job"
        assert data["scale_factor"] == 10

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api._submit_dsdgen_job", return_value="99999")
    def test_sf100_job_path(self, mock_submit, mock_db, mock_wc):
        mock_db.fetch_one.side_effect = [
            None,
            _tpcds_row(id=4, scale_factor=100),
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "tpcds_sf100",
                "schema_name": "sf100",
                "scale_factor": 100,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["method"] == "job"

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client", MagicMock())
    @patch("tpcds_api.db")
    def test_invalid_scale_factor(self, mock_db):
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "test",
                "schema_name": "sf5",
                "scale_factor": 5,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 400
        assert "scale_factor" in resp.json()["detail"]

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client", MagicMock())
    @patch("tpcds_api.db")
    def test_duplicate_ready_catalog_rejected(self, mock_db):
        """A catalog with status='ready' blocks re-creation (409)."""
        mock_db.fetch_one.return_value = {"id": 1, "status": "ready"}
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "existing_cat",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api.check_samples_available", return_value=True)
    @patch("tpcds_api.threading.Thread")
    def test_retry_after_failed_deletes_stale_record(
        self, mock_thread, mock_samples, mock_db, mock_wc
    ):
        """A catalog with status='failed' is deleted to allow retry."""
        mock_db.fetch_one.side_effect = [
            {"id": 99, "status": "failed"},  # duplicate check — stale
            _tpcds_row(id=100, status="creating"),  # insert
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "retry_cat",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == 100
        # Verify the stale record was deleted
        delete_calls = [c for c in mock_db.execute.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1
        assert delete_calls[0][0][1] == (99,)

    @patch("main._warehouse_id", "wh-123")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    @patch("tpcds_api.check_samples_available", return_value=True)
    @patch("tpcds_api.threading.Thread")
    def test_retry_after_creating_deletes_stale_record(
        self, mock_thread, mock_samples, mock_db, mock_wc
    ):
        """A catalog with status='creating' (orphaned) is deleted to allow retry."""
        mock_db.fetch_one.side_effect = [
            {"id": 50, "status": "creating"},  # stale 'creating'
            _tpcds_row(id=51, status="creating"),  # new insert
        ]
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "orphan_cat",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_admin_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == 51

    def test_403_for_non_admin(self):
        resp = client.post(
            "/api/tpcds/create",
            json={
                "catalog_name": "test",
                "schema_name": "sf1",
                "scale_factor": 1,
            },
            headers=_user_header(),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# _sf1_ctas_sync  (T90 — unit test the background function)
# ---------------------------------------------------------------------------


class TestSf1CtasSync:
    @patch("tpcds_api.db")
    @patch("tpcds_api._execute_sql")
    def test_successful_creation(self, mock_exec_sql, mock_db):
        wc = MagicMock()
        wc.current_user.me.return_value = _mock_me()
        wc.catalogs.update.return_value = None

        tpcds_api._sf1_ctas_sync(1, "mycat", "sf1", wc, "wh-123")

        # Should call CREATE CATALOG, CREATE SCHEMA, and 25 CTAS statements + 1 GRANT
        assert mock_exec_sql.call_count == 28  # 2 + 25 + 1 (grant)
        # Should update tables_created 25 times
        assert mock_db.execute.call_count >= 25
        # Final status should be 'ready'
        calls = [str(c) for c in mock_db.execute.call_args_list]
        ready_calls = [c for c in calls if "ready" in c]
        assert len(ready_calls) >= 1

    @patch("tpcds_api.db")
    @patch("tpcds_api._execute_sql")
    def test_dbgen_version_skipped_gracefully(self, mock_exec_sql, mock_db):
        """If dbgen_version doesn't exist in samples, skip it without failing."""
        wc = MagicMock()
        wc.current_user.me.return_value = _mock_me()

        def side_effect(wc_arg, wh_id, sql):
            if "dbgen_version" in sql and "SELECT" in sql:
                raise Exception("TABLE_OR_VIEW_NOT_FOUND")

        mock_exec_sql.side_effect = side_effect

        tpcds_api._sf1_ctas_sync(1, "mycat", "sf1", wc, "wh-123")

        # Should still mark as ready (dbgen_version skip is non-fatal)
        calls = [str(c) for c in mock_db.execute.call_args_list]
        ready_calls = [c for c in calls if "ready" in c]
        assert len(ready_calls) >= 1

    @patch("tpcds_api.db")
    @patch("tpcds_api._execute_sql")
    def test_non_dbgen_error_causes_failure(self, mock_exec_sql, mock_db):
        """A failure on a non-dbgen_version table should mark as failed."""
        wc = MagicMock()
        wc.current_user.me.return_value = _mock_me()

        call_count = [0]

        def side_effect(wc_arg, wh_id, sql):
            call_count[0] += 1
            # Fail on the 5th table (customer)
            if call_count[0] == 5:
                raise Exception("Disk full")

        mock_exec_sql.side_effect = side_effect

        tpcds_api._sf1_ctas_sync(1, "mycat", "sf1", wc, "wh-123")

        # Should mark as failed
        calls = [str(c) for c in mock_db.execute.call_args_list]
        failed_calls = [c for c in calls if "failed" in c]
        assert len(failed_calls) >= 1


# ---------------------------------------------------------------------------
# _build_dsdgen_script  (T91 — unit test)
# ---------------------------------------------------------------------------


class TestBuildDsdgenScript:
    def test_contains_correct_sf(self):
        script = tpcds_api._build_dsdgen_script("mycat", "sf10", 10)
        assert "sf = 10" in script
        assert "mycat" in script
        assert "sf10" in script

    def test_contains_duckdb_install(self):
        script = tpcds_api._build_dsdgen_script("cat1", "sch1", 100)
        assert "pip" in script
        assert "duckdb" in script

    def test_contains_spark_write(self):
        script = tpcds_api._build_dsdgen_script("cat1", "sch1", 10)
        assert "saveAsTable" in script
        assert "delta" in script

    def test_excludes_dbgen_version(self):
        script = tpcds_api._build_dsdgen_script("cat1", "sch1", 10)
        # dbgen_version should NOT be in the tables list
        assert "dbgen_version" not in script


# ---------------------------------------------------------------------------
# _get_cluster_spec  (T91 — unit test)
# ---------------------------------------------------------------------------


class TestGetClusterSpec:
    def test_sf10_spec(self):
        spec = tpcds_api._get_cluster_spec(10)
        assert spec["node_type_id"] == "Standard_D4s_v5"
        assert spec["num_workers"] == 0

    def test_sf100_spec(self):
        spec = tpcds_api._get_cluster_spec(100)
        assert spec["node_type_id"] == "Standard_D16s_v5"
        assert spec["num_workers"] == 0

    def test_sf1_uses_small_spec(self):
        spec = tpcds_api._get_cluster_spec(1)
        assert spec["node_type_id"] == "Standard_D4s_v5"


# ---------------------------------------------------------------------------
# GET /api/tpcds/status/{tpcds_id}  (T92)
# ---------------------------------------------------------------------------


class TestGetTpcdsStatus:
    @patch("tpcds_api.db")
    def test_returns_record(self, mock_db):
        mock_db.fetch_one.return_value = _tpcds_row(status="ready", tables_created=25)
        resp = client.get("/api/tpcds/status/1", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["tables_created"] == 25

    @patch("tpcds_api.db")
    def test_not_found(self, mock_db):
        mock_db.fetch_one.return_value = None
        resp = client.get("/api/tpcds/status/999", headers=_admin_header())
        assert resp.status_code == 404

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_polls_running_job(self, mock_db, mock_wc):
        mock_db.fetch_one.return_value = _tpcds_row(
            status="creating", job_run_id="12345"
        )
        mock_wc.api_client.do.return_value = {
            "state": {
                "life_cycle_state": "RUNNING",
                "result_state": None,
            },
            "start_time": int(time.time() * 1000) - 60000,
        }
        resp = client.get("/api/tpcds/status/1", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_state"] == "RUNNING"
        assert data["status"] == "creating"
        assert "elapsed_time_seconds" in data

    @patch("tpcds_api._finalize_job_success")
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_polls_completed_job(self, mock_db, mock_wc, mock_finalize):
        mock_db.fetch_one.return_value = _tpcds_row(
            status="creating", job_run_id="12345"
        )
        mock_wc.api_client.do.return_value = {
            "state": {
                "life_cycle_state": "TERMINATED",
                "result_state": "SUCCESS",
            },
            "start_time": int(time.time() * 1000) - 120000,
        }
        resp = client.get("/api/tpcds/status/1", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        mock_finalize.assert_called_once()

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_polls_failed_job(self, mock_db, mock_wc):
        mock_db.fetch_one.return_value = _tpcds_row(
            status="creating", job_run_id="12345"
        )
        mock_wc.api_client.do.return_value = {
            "state": {
                "life_cycle_state": "TERMINATED",
                "result_state": "FAILED",
                "state_message": "OutOfMemoryError",
            },
        }
        resp = client.get("/api/tpcds/status/1", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "OutOfMemoryError" in data["error_message"]

    @patch("tpcds_api.db")
    def test_sf1_creating_no_job(self, mock_db):
        """SF1 CTAS path — no job_run_id, returns current record."""
        mock_db.fetch_one.return_value = _tpcds_row(
            status="creating", job_run_id=None, tables_created=12
        )
        resp = client.get("/api/tpcds/status/1", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "creating"
        assert data["tables_created"] == 12
        assert data.get("job_state") is None

    def test_403_for_non_admin(self):
        resp = client.get("/api/tpcds/status/1", headers=_user_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/tpcds/catalogs  (T93)
# ---------------------------------------------------------------------------


class TestListTpcdsCatalogs:
    @patch("tpcds_api.db")
    def test_empty_list(self, mock_db):
        mock_db.fetch_all.return_value = []
        resp = client.get("/api/tpcds/catalogs", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("tpcds_api.db")
    def test_returns_catalogs(self, mock_db):
        mock_db.fetch_all.return_value = [
            _tpcds_row(id=1, catalog_name="tpcds_sf1", status="ready"),
            _tpcds_row(
                id=2, catalog_name="tpcds_sf10", status="creating", scale_factor=10
            ),
        ]
        resp = client.get("/api/tpcds/catalogs", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["catalog_name"] == "tpcds_sf1"
        assert data[1]["catalog_name"] == "tpcds_sf10"

    def test_403_for_non_admin(self):
        resp = client.get("/api/tpcds/catalogs", headers=_user_header())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/tpcds/catalogs/{catalog_name}  (T93)
# ---------------------------------------------------------------------------


class TestDeleteTpcdsCatalog:
    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_delete_success(self, mock_db, mock_wc):
        mock_db.fetch_one.return_value = _tpcds_row(
            catalog_name="tpcds_sf1", status="ready"
        )
        mock_wc.catalogs.delete.return_value = None
        resp = client.delete("/api/tpcds/catalogs/tpcds_sf1", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert resp.json()["catalog_name"] == "tpcds_sf1"
        mock_wc.catalogs.delete.assert_called_once_with("tpcds_sf1", force=True)

    @patch("main._workspace_client", MagicMock())
    @patch("tpcds_api.db")
    def test_reject_non_system_catalog(self, mock_db):
        mock_db.fetch_one.return_value = None  # not in tpcds_catalogs
        resp = client.delete(
            "/api/tpcds/catalogs/production_data", headers=_admin_header()
        )
        assert resp.status_code == 404
        assert "not created by Delta Router" in resp.json()["detail"]

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_already_deleted_in_databricks(self, mock_db, mock_wc):
        """Catalog exists in DB but not in Databricks — clean up gracefully."""
        mock_db.fetch_one.return_value = _tpcds_row(catalog_name="old_cat")
        mock_wc.catalogs.delete.side_effect = Exception("Catalog not found")
        resp = client.delete("/api/tpcds/catalogs/old_cat", headers=_admin_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_403_for_non_admin(self):
        resp = client.delete("/api/tpcds/catalogs/test", headers=_user_header())
        assert resp.status_code == 403

    def test_503_when_not_configured(self):
        with patch("main._workspace_client", None):
            resp = client.delete("/api/tpcds/catalogs/test", headers=_admin_header())
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# TPCDS_TABLES constant  (sanity check)
# ---------------------------------------------------------------------------


class TestTpcdsTablesConstant:
    def test_25_tables(self):
        assert len(tpcds_api.TPCDS_TABLES) == 25

    def test_includes_key_tables(self):
        assert "store_sales" in tpcds_api.TPCDS_TABLES
        assert "customer" in tpcds_api.TPCDS_TABLES
        assert "inventory" in tpcds_api.TPCDS_TABLES
        assert "dbgen_version" in tpcds_api.TPCDS_TABLES
        assert "date_dim" in tpcds_api.TPCDS_TABLES

    def test_no_duplicates(self):
        assert len(set(tpcds_api.TPCDS_TABLES)) == len(tpcds_api.TPCDS_TABLES)


# ---------------------------------------------------------------------------
# GET /api/tpcds/detect — detect TPC-DS scale factors
# ---------------------------------------------------------------------------


class TestDetectTpcds:
    """GET /api/tpcds/detect — detect available scale factors."""

    def test_requires_auth(self):
        resp = client.get("/api/tpcds/detect")
        assert resp.status_code == 401

    @patch.object(_main_module, "_workspace_client", None)
    def test_no_workspace_returns_all_false(self):
        resp = client.get("/api/tpcds/detect", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"sf1": False, "sf10": False, "sf100": False}

    @patch.object(_main_module, "_workspace_client")
    def test_all_schemas_exist(self, mock_wc):
        """All 3 scale factors detected."""
        mock_wc.schemas.get.return_value = MagicMock()  # no exception = exists
        resp = client.get("/api/tpcds/detect", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"sf1": True, "sf10": True, "sf100": True}
        assert mock_wc.schemas.get.call_count == 3

    @patch.object(_main_module, "_workspace_client")
    def test_mixed_results(self, mock_wc):
        """sf1 exists, sf10 missing, sf100 exists."""

        def schema_side_effect(full_name):
            if full_name.endswith(".sf10"):
                raise Exception("NOT_FOUND")
            return MagicMock()

        mock_wc.schemas.get.side_effect = schema_side_effect
        resp = client.get("/api/tpcds/detect", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["sf1"] is True
        assert data["sf10"] is False
        assert data["sf100"] is True

    @patch.object(_main_module, "_workspace_client")
    def test_all_missing(self, mock_wc):
        """Catalog doesn't exist — all SFs false."""
        mock_wc.schemas.get.side_effect = Exception("CATALOG_DOES_NOT_EXIST")
        resp = client.get("/api/tpcds/detect", headers=_admin_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"sf1": False, "sf10": False, "sf100": False}


# ---------------------------------------------------------------------------
# _create_tpcds_collection — auto-create query collection (Phase 16)
# ---------------------------------------------------------------------------


class TestCreateTpcdsCollection:
    """Unit tests for _create_tpcds_collection helper."""

    @patch("tpcds_api.db")
    def test_creates_collection_with_99_queries(self, mock_db):
        """On first call, creates a new collection with 99 queries."""
        # No existing collection
        mock_db.fetch_one.side_effect = [
            None,  # SELECT id FROM collections WHERE name = ...
            {"id": 42},  # INSERT INTO collections ... RETURNING id
        ]
        mock_db.execute.return_value = None

        result = tpcds_api._create_tpcds_collection(1, "mycat", "sf1", 1)

        assert result == 42
        # Should insert collection
        insert_call = mock_db.fetch_one.call_args_list[1]
        assert "INSERT INTO collections" in insert_call[0][0]
        assert insert_call[0][1][0] == "TPC-DS SF1"
        assert "tpcds" in insert_call[0][0]  # tag = 'tpcds'

        # Should insert 99 queries + 1 update to tpcds_catalogs = 100 execute calls
        execute_calls = mock_db.execute.call_args_list
        query_inserts = [c for c in execute_calls if "collection_queries" in str(c)]
        assert len(query_inserts) == 99

        # Should link collection to tpcds_catalogs
        link_calls = [c for c in execute_calls if "tpcds_catalogs" in str(c)]
        assert len(link_calls) == 1
        assert link_calls[0][0][1] == (42, 1)  # (collection_id, record_id)

    @patch("tpcds_api.db")
    def test_idempotent_reuses_existing_collection(self, mock_db):
        """If collection already exists, reuses it without inserting queries."""
        mock_db.fetch_one.return_value = {"id": 7}  # existing collection
        mock_db.execute.return_value = None

        result = tpcds_api._create_tpcds_collection(1, "mycat", "sf1", 1)

        assert result == 7
        # Should NOT insert any queries (only update tpcds_catalogs.collection_id)
        execute_calls = mock_db.execute.call_args_list
        query_inserts = [c for c in execute_calls if "collection_queries" in str(c)]
        assert len(query_inserts) == 0
        # Should link to tpcds_catalogs
        link_calls = [c for c in execute_calls if "tpcds_catalogs" in str(c)]
        assert len(link_calls) == 1

    @patch("tpcds_api.db")
    def test_collection_name_matches_scale_factor(self, mock_db):
        """Collection name includes the scale factor."""
        mock_db.fetch_one.side_effect = [None, {"id": 10}]
        mock_db.execute.return_value = None

        tpcds_api._create_tpcds_collection(1, "mycat", "sf10", 10)

        check_call = mock_db.fetch_one.call_args_list[0]
        assert check_call[0][1] == ("TPC-DS SF10",)

    @patch("tpcds_api.db")
    def test_error_returns_none_and_logs(self, mock_db):
        """On error, returns None without raising."""
        mock_db.fetch_one.side_effect = Exception("DB connection lost")

        result = tpcds_api._create_tpcds_collection(1, "mycat", "sf1", 1)

        assert result is None

    @patch("tpcds_api.db")
    def test_queries_are_rewritten_for_catalog_schema(self, mock_db):
        """Inserted queries use the correct catalog.schema three-part names."""
        mock_db.fetch_one.side_effect = [None, {"id": 50}]
        mock_db.execute.return_value = None

        tpcds_api._create_tpcds_collection(1, "delta_router_tpcds", "sf1", 1)

        # Check the first query insert has three-part names
        query_inserts = [
            c for c in mock_db.execute.call_args_list if "collection_queries" in str(c)
        ]
        first_sql = query_inserts[0][0][1][1]  # (collection_id, sql, seq)
        assert "delta_router_tpcds.sf1." in first_sql
        assert "__CATALOG__" not in first_sql
        assert "__SCHEMA__" not in first_sql


# ---------------------------------------------------------------------------
# _sf1_ctas_sync — collection creation hook (Phase 16)
# ---------------------------------------------------------------------------


class TestSf1CtasSyncCollectionCreation:
    """Verify _sf1_ctas_sync calls _create_tpcds_collection on success."""

    @patch("tpcds_api._create_tpcds_collection")
    @patch("tpcds_api.db")
    @patch("tpcds_api._execute_sql")
    def test_creates_collection_after_success(
        self, mock_exec_sql, mock_db, mock_create_coll
    ):
        wc = MagicMock()
        wc.current_user.me.return_value = _mock_me()

        tpcds_api._sf1_ctas_sync(1, "mycat", "sf1", wc, "wh-123")

        mock_create_coll.assert_called_once_with(1, "mycat", "sf1", 1)

    @patch("tpcds_api._create_tpcds_collection")
    @patch("tpcds_api.db")
    @patch("tpcds_api._execute_sql")
    def test_no_collection_on_failure(self, mock_exec_sql, mock_db, mock_create_coll):
        """If CTAS fails, _create_tpcds_collection is NOT called."""
        wc = MagicMock()
        wc.current_user.me.return_value = _mock_me()
        # Fail on the 3rd call (first table CTAS)
        call_count = [0]

        def side_effect(wc_arg, wh_id, sql):
            call_count[0] += 1
            if call_count[0] == 3:
                raise Exception("SQL error")

        mock_exec_sql.side_effect = side_effect

        tpcds_api._sf1_ctas_sync(1, "mycat", "sf1", wc, "wh-123")

        mock_create_coll.assert_not_called()


# ---------------------------------------------------------------------------
# _finalize_job_success — collection creation hook (Phase 16)
# ---------------------------------------------------------------------------


class TestFinalizeJobSuccessCollectionCreation:
    """Verify _finalize_job_success calls _create_tpcds_collection."""

    @patch("tpcds_api._create_tpcds_collection")
    @patch("tpcds_api.db")
    def test_creates_collection_for_job_success(self, mock_db, mock_create_coll):
        wc = MagicMock()
        # First execute (status update) then fetch_one (scale_factor lookup)
        mock_db.fetch_one.return_value = {"scale_factor": 10}

        tpcds_api._finalize_job_success(5, "mycat", "sf10", wc)

        mock_create_coll.assert_called_once_with(5, "mycat", "sf10", 10)

    @patch("tpcds_api._create_tpcds_collection")
    @patch("tpcds_api.db")
    def test_no_collection_if_row_missing(self, mock_db, mock_create_coll):
        """If tpcds_catalogs row not found (shouldn't happen), skip gracefully."""
        wc = MagicMock()
        mock_db.fetch_one.return_value = None

        tpcds_api._finalize_job_success(99, "mycat", "sf100", wc)

        mock_create_coll.assert_not_called()


# ---------------------------------------------------------------------------
# Cascade delete — collection deletion on catalog delete (Phase 16)
# ---------------------------------------------------------------------------


class TestCascadeDeleteCollection:
    """Verify delete_tpcds_catalog cascades to linked collection."""

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_deletes_linked_collection(self, mock_db, mock_wc):
        """When collection_id is set, cascade delete removes the collection."""
        row = _tpcds_row(catalog_name="tpcds_sf1", status="ready")
        row["collection_id"] = 42
        mock_db.fetch_one.return_value = row
        mock_wc.catalogs.delete.return_value = None

        resp = client.delete("/api/tpcds/catalogs/tpcds_sf1", headers=_admin_header())

        assert resp.status_code == 200
        # Should delete collection
        execute_calls = [str(c) for c in mock_db.execute.call_args_list]
        collection_deletes = [
            c for c in execute_calls if "DELETE FROM collections" in c
        ]
        assert len(collection_deletes) == 1
        assert "42" in collection_deletes[0]

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_no_cascade_when_collection_id_null(self, mock_db, mock_wc):
        """When collection_id is NULL, no collection cascade attempted."""
        row = _tpcds_row(catalog_name="tpcds_sf1", status="ready")
        row["collection_id"] = None
        mock_db.fetch_one.return_value = row
        mock_wc.catalogs.delete.return_value = None

        resp = client.delete("/api/tpcds/catalogs/tpcds_sf1", headers=_admin_header())

        assert resp.status_code == 200
        execute_calls = [str(c) for c in mock_db.execute.call_args_list]
        collection_deletes = [
            c for c in execute_calls if "DELETE FROM collections" in c
        ]
        assert len(collection_deletes) == 0

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_no_cascade_when_collection_id_missing(self, mock_db, mock_wc):
        """When row has no collection_id key (old schema), no cascade."""
        row = _tpcds_row(catalog_name="tpcds_sf1", status="ready")
        # _tpcds_row doesn't include collection_id — simulates old schema
        mock_db.fetch_one.return_value = row
        mock_wc.catalogs.delete.return_value = None

        resp = client.delete("/api/tpcds/catalogs/tpcds_sf1", headers=_admin_header())

        assert resp.status_code == 200
        execute_calls = [str(c) for c in mock_db.execute.call_args_list]
        collection_deletes = [
            c for c in execute_calls if "DELETE FROM collections" in c
        ]
        assert len(collection_deletes) == 0

    @patch("main._workspace_client")
    @patch("tpcds_api.db")
    def test_cascade_error_does_not_fail_delete(self, mock_db, mock_wc):
        """If cascade delete fails, the catalog delete still succeeds."""
        row = _tpcds_row(catalog_name="tpcds_sf1", status="ready")
        row["collection_id"] = 42
        mock_db.fetch_one.return_value = row
        mock_wc.catalogs.delete.return_value = None

        # Make collection DELETE fail, but other executes succeed
        def execute_side_effect(sql, params=None):
            if "DELETE FROM collections" in sql:
                raise Exception("FK violation")
            return None

        mock_db.execute.side_effect = execute_side_effect

        resp = client.delete("/api/tpcds/catalogs/tpcds_sf1", headers=_admin_header())

        # Should still succeed — cascade error is non-fatal
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
