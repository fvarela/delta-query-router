"""Tests for benchmarks_api.py — benchmark definitions + runs CRUD and execution."""

import json
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import auth
import benchmarks_api
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-benchmarks"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


_NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _collection_row(id=1):
    return {
        "id": id,
        "name": "Test Collection",
        "description": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _query_row(id=1, collection_id=1, seq=1, sql="SELECT 1"):
    return {
        "id": id,
        "collection_id": collection_id,
        "query_text": sql,
        "sequence_number": seq,
    }


def _engine_row(id="duckdb-1", engine_type="duckdb", active=True):
    return {
        "id": id,
        "engine_type": engine_type,
        "display_name": f"Engine {id}",
        "config": {},
        "k8s_service_name": "duckdb-worker" if engine_type == "duckdb" else None,
        "cost_tier": 3,
        "is_active": active,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _definition_row(id=1, collection_id=1, engine_id="duckdb-1"):
    return {
        "id": id,
        "collection_id": collection_id,
        "engine_id": engine_id,
        "created_at": _NOW,
    }


def _run_row(id=1, definition_id=1, status="warming_up"):
    return {
        "id": id,
        "definition_id": definition_id,
        "status": status,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ---------------------------------------------------------------------------
# POST /api/benchmarks — creation + execution
# ---------------------------------------------------------------------------


class TestCreateBenchmark:
    """POST /api/benchmarks — benchmark creation and execution flow."""

    def test_requires_auth(self):
        resp = client.post(
            "/api/benchmarks", json={"collection_id": 1, "engine_ids": ["duckdb-1"]}
        )
        assert resp.status_code == 401

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_collection_not_found(self, mock_fetch):
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 999, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 404
        assert "Collection" in resp.json()["detail"]

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    @patch("benchmarks_api.db.fetch_one", return_value=_collection_row())
    def test_empty_collection(self, mock_one, mock_all):
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "no queries" in resp.json()["detail"].lower()

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_engine_not_found(self, mock_one, mock_all):
        # First call returns collection, second returns None (engine not found)
        mock_one.side_effect = [_collection_row(), None]
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["nonexistent"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 404
        assert "Engine" in resp.json()["detail"]

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_engine_not_active(self, mock_one, mock_all):
        mock_one.side_effect = [_collection_row(), _engine_row(active=False)]
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "not active" in resp.json()["detail"].lower()

    @patch("benchmarks_api.db.fetch_all", return_value=[_query_row()])
    @patch("benchmarks_api.db.fetch_one")
    def test_no_engines(self, mock_one, mock_all):
        mock_one.return_value = _collection_row()
        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "No engines" in resp.json()["detail"]

    @patch("benchmarks_api._warmup_duckdb", new_callable=AsyncMock, return_value=50.0)
    @patch("benchmarks_api._execute_query_on_duckdb", new_callable=AsyncMock)
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_success_single_engine(
        self, mock_one, mock_all, mock_exec, mock_run_query, mock_warmup
    ):
        """Full flow: 1 DuckDB engine, 1 query → complete."""
        mock_run_query.return_value = {"execution_time_ms": 12.5, "error_message": None}

        # fetch_one calls: collection, engine, definition (get_or_create), run
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _definition_row(id=10),  # _get_or_create_definition SELECT hit
            _run_row(id=42, definition_id=10),  # INSERT run
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["run_ids"] == [42]
        assert data["status"] == "complete"

        # Verify warmup was called
        mock_warmup.assert_called_once()

        # Verify db.execute was called for:
        # warmup insert, status→running, result insert, status→complete
        exec_calls = mock_exec.call_args_list
        assert len(exec_calls) == 4

        exec_sqls = [c[0][0] for c in exec_calls]
        assert any("benchmark_engine_warmups" in s for s in exec_sqls)
        assert any("benchmark_results" in s for s in exec_sqls)
        assert any("running" in s for s in exec_sqls)
        assert any("complete" in s for s in exec_sqls)

    @patch(
        "benchmarks_api._warmup_duckdb",
        new_callable=AsyncMock,
        side_effect=Exception("Connection refused"),
    )
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_warmup_failure(self, mock_one, mock_all, mock_exec, mock_warmup):
        """Warmup failure → run marked 'failed'."""
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _definition_row(id=5),
            _run_row(id=10, definition_id=5),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["run_ids"] == [10]
        assert data["status"] == "failed"
        assert "Warmup failed" in data["error"]

        # Verify failed status was written
        status_calls = [c for c in mock_exec.call_args_list if "failed" in str(c)]
        assert len(status_calls) >= 1

    @patch("benchmarks_api._warmup_duckdb", new_callable=AsyncMock, return_value=20.0)
    @patch("benchmarks_api._execute_query_on_duckdb", new_callable=AsyncMock)
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_query_failure_continues(
        self, mock_one, mock_all, mock_exec, mock_run_query, mock_warmup
    ):
        """One query fails → error recorded, run still completes."""
        queries = [
            _query_row(id=1, seq=1, sql="SELECT 1"),
            _query_row(id=2, seq=2, sql="SELECT bad"),
        ]
        mock_run_query.side_effect = [
            {"execution_time_ms": 5.0, "error_message": None},
            {"execution_time_ms": 1.0, "error_message": "Parser Error"},
        ]

        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _definition_row(id=3),
            _run_row(id=7, definition_id=3),
        ]
        mock_all.return_value = queries

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        assert resp.json()["status"] == "complete"

        # Both results should be inserted (2 result INSERTs)
        result_inserts = [
            c for c in mock_exec.call_args_list if "benchmark_results" in c[0][0]
        ]
        assert len(result_inserts) == 2

    @patch("benchmarks_api._warmup_duckdb", new_callable=AsyncMock, return_value=10.0)
    @patch("benchmarks_api._execute_query_on_duckdb", new_callable=AsyncMock)
    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_multiple_engines(
        self, mock_one, mock_all, mock_exec, mock_run_query, mock_warmup
    ):
        """2 engines × 1 query = 2 warmups + 2 results, 2 run_ids returned."""
        mock_run_query.return_value = {"execution_time_ms": 8.0, "error_message": None}

        mock_one.side_effect = [
            _collection_row(),
            _engine_row(id="duckdb-1"),
            _engine_row(id="duckdb-2"),
            # get_or_create for engine 1
            _definition_row(id=1, engine_id="duckdb-1"),
            # run for engine 1
            _run_row(id=90, definition_id=1),
            # get_or_create for engine 2
            _definition_row(id=2, engine_id="duckdb-2"),
            # run for engine 2
            _run_row(id=91, definition_id=2),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1", "duckdb-2"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "complete"
        assert len(data["run_ids"]) == 2
        assert 90 in data["run_ids"]
        assert 91 in data["run_ids"]

        # 2 warmup calls
        assert mock_warmup.call_count == 2
        # 2 query executions
        assert mock_run_query.call_count == 2


# ---------------------------------------------------------------------------
# GET /api/benchmarks — list definitions
# ---------------------------------------------------------------------------


class TestListDefinitions:
    """GET /api/benchmarks — list benchmark definitions."""

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_list_empty(self, mock_all):
        resp = client.get("/api/benchmarks", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("benchmarks_api.db.fetch_one", return_value=None)  # no latest_run
    @patch("benchmarks_api.db.fetch_all")
    def test_list_returns_definitions(self, mock_all, mock_one):
        mock_all.return_value = [
            {
                "id": 1,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "C1",
                "engine_display_name": "DuckDB Small",
                "run_count": 3,
                "created_at": _NOW,
            },
        ]
        resp = client.get("/api/benchmarks", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["collection_name"] == "C1"
        assert data[0]["run_count"] == 3
        assert data[0]["latest_run"] is None

    @patch("benchmarks_api.db.fetch_one")
    @patch("benchmarks_api.db.fetch_all")
    def test_list_with_latest_run(self, mock_all, mock_one):
        mock_all.return_value = [
            {
                "id": 1,
                "collection_id": 1,
                "engine_id": "duckdb-1",
                "collection_name": "C1",
                "engine_display_name": "DuckDB Small",
                "run_count": 1,
                "created_at": _NOW,
            },
        ]
        mock_one.return_value = _run_row(id=5, definition_id=1, status="complete")
        resp = client.get("/api/benchmarks", headers=_auth_header())
        data = resp.json()
        assert data[0]["latest_run"]["id"] == 5
        assert data[0]["latest_run"]["status"] == "complete"

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_filter_by_collection_id(self, mock_all):
        resp = client.get("/api/benchmarks?collection_id=5", headers=_auth_header())
        assert resp.status_code == 200
        sql = mock_all.call_args[0][0]
        assert "collection_id" in sql

    @patch("benchmarks_api.db.fetch_all", return_value=[])
    def test_filter_by_engine_id(self, mock_all):
        resp = client.get("/api/benchmarks?engine_id=duckdb-1", headers=_auth_header())
        assert resp.status_code == 200
        sql = mock_all.call_args[0][0]
        assert "engine_id" in sql

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id} — definition detail
# ---------------------------------------------------------------------------


class TestGetDefinition:
    """GET /api/benchmarks/{id} — definition with runs."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_get_with_runs(self, mock_one, mock_all):
        mock_one.return_value = {
            "id": 1,
            "collection_id": 1,
            "engine_id": "duckdb-1",
            "collection_name": "Test",
            "engine_display_name": "DuckDB Small",
            "created_at": _NOW,
        }
        mock_all.return_value = [
            _run_row(id=10, definition_id=1, status="complete"),
            _run_row(id=11, definition_id=1, status="running"),
        ]

        resp = client.get("/api/benchmarks/1", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["collection_name"] == "Test"
        assert data["run_count"] == 2
        assert len(data["runs"]) == 2

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id}/runs — list runs
# ---------------------------------------------------------------------------


class TestListRuns:
    """GET /api/benchmarks/{id}/runs — runs for a definition."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_list_runs(self, mock_one, mock_all):
        mock_one.return_value = _definition_row(id=1)
        mock_all.return_value = [
            _run_row(id=10, definition_id=1, status="complete"),
        ]
        resp = client.get("/api/benchmarks/1/runs", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 10

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_definition_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/999/runs", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/1/runs")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id}/runs/{run_id} — run detail
# ---------------------------------------------------------------------------


class TestGetRun:
    """GET /api/benchmarks/{id}/runs/{run_id} — run with warmups and results."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_get_run_detail(self, mock_one, mock_all):
        mock_one.return_value = _run_row(id=10, definition_id=1, status="complete")
        mock_all.side_effect = [
            # warmups
            [
                {
                    "id": 1,
                    "run_id": 10,
                    "engine_id": "duckdb-1",
                    "engine_display_name": "DuckDB Small",
                    "cold_start_time_ms": 50.0,
                    "started_at": _NOW,
                }
            ],
            # results
            [
                {
                    "id": 1,
                    "run_id": 10,
                    "engine_id": "duckdb-1",
                    "engine_display_name": "DuckDB Small",
                    "query_id": 1,
                    "query_text": "SELECT 1",
                    "sequence_number": 1,
                    "execution_time_ms": 12.0,
                    "io_latency_ms": None,
                    "error_message": None,
                }
            ],
        ]

        resp = client.get("/api/benchmarks/1/runs/10", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert len(data["warmups"]) == 1
        assert data["warmups"][0]["cold_start_time_ms"] == 50.0
        assert len(data["results"]) == 1
        assert data["results"][0]["execution_time_ms"] == 12.0

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_run_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/1/runs/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks/1/runs/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/benchmarks/{id} — delete definition
# ---------------------------------------------------------------------------


class TestDeleteDefinition:
    """DELETE /api/benchmarks/{id} — cascade delete definition."""

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_delete_existing(self, mock_one, mock_exec):
        mock_one.return_value = _definition_row(id=5)
        resp = client.delete("/api/benchmarks/5", headers=_auth_header())
        assert resp.status_code == 204
        mock_exec.assert_called_once()

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_delete_not_found(self, mock_one):
        resp = client.delete("/api/benchmarks/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.delete("/api/benchmarks/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/benchmarks/{id}/runs/{run_id} — delete single run
# ---------------------------------------------------------------------------


class TestDeleteRun:
    """DELETE /api/benchmarks/{id}/runs/{run_id} — cascade delete run."""

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_delete_existing(self, mock_one, mock_exec):
        mock_one.return_value = _run_row(id=10, definition_id=1)
        resp = client.delete("/api/benchmarks/1/runs/10", headers=_auth_header())
        assert resp.status_code == 204
        mock_exec.assert_called_once()

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_delete_not_found(self, mock_one):
        resp = client.delete("/api/benchmarks/1/runs/999", headers=_auth_header())
        assert resp.status_code == 404

    def test_requires_auth(self):
        resp = client.delete("/api/benchmarks/1/runs/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Internal helper unit tests
# ---------------------------------------------------------------------------


class TestExecuteQueryOnDuckdb:
    """_execute_query_on_duckdb — targeted DuckDB execution."""

    @pytest.mark.anyio
    async def test_success(self):
        engine = _engine_row()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": ["1"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 3.5,
        }
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch("benchmarks_api.httpx.AsyncClient", return_value=mock_client):
            result = await benchmarks_api._execute_query_on_duckdb(engine, "SELECT 1")

        assert result["execution_time_ms"] == 3.5
        assert result["error_message"] is None

    @pytest.mark.anyio
    async def test_http_error(self):
        engine = _engine_row()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad query"
        mock_resp.json.return_value = {"detail": "Parser Error"}
        mock_resp.headers = {"content-type": "application/json"}
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch("benchmarks_api.httpx.AsyncClient", return_value=mock_client):
            result = await benchmarks_api._execute_query_on_duckdb(engine, "BAD SQL")

        assert result["error_message"] is not None
        assert "Parser Error" in result["error_message"]

    @pytest.mark.anyio
    async def test_connection_error(self):
        engine = _engine_row()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Connection refused")

        with patch("benchmarks_api.httpx.AsyncClient", return_value=mock_client):
            result = await benchmarks_api._execute_query_on_duckdb(engine, "SELECT 1")

        assert result["error_message"] is not None
        assert "Connection refused" in result["error_message"]


# ---------------------------------------------------------------------------
# _lookup_io_latency_ms unit tests
# ---------------------------------------------------------------------------


class TestLookupIoLatencyMs:
    """_lookup_io_latency_ms — probe lookup for benchmark results."""

    @patch("benchmarks_api.db")
    def test_no_tables_returns_none(self, mock_db):
        """SELECT 1 has no tables → None."""
        result = benchmarks_api._lookup_io_latency_ms("SELECT 1")
        assert result is None
        mock_db.fetch_one.assert_not_called()

    @patch("benchmarks_api.db")
    def test_unparseable_sql_returns_none(self, mock_db):
        """Garbage SQL → None (graceful fallback)."""
        result = benchmarks_api._lookup_io_latency_ms("NOT VALID SQL AT ALL !!!")
        assert result is None

    @patch("benchmarks_api.db")
    def test_table_not_in_cache_returns_none(self, mock_db):
        """Table not found in metadata cache → None."""
        mock_db.fetch_one.return_value = None
        result = benchmarks_api._lookup_io_latency_ms("SELECT * FROM cat.sch.my_table")
        assert result is None

    @patch("benchmarks_api.db")
    def test_no_storage_location_returns_none(self, mock_db):
        """Cached table has no storage_location → None."""
        mock_db.fetch_one.return_value = {"storage_location": None}
        result = benchmarks_api._lookup_io_latency_ms("SELECT * FROM cat.sch.my_table")
        assert result is None

    @patch("benchmarks_api.db")
    def test_no_probe_returns_none(self, mock_db):
        """Table has storage_location but no probe data → None."""
        mock_db.fetch_one.side_effect = [
            {"storage_location": "s3://bucket/table"},  # metadata cache
            None,  # no probe
        ]
        result = benchmarks_api._lookup_io_latency_ms("SELECT * FROM cat.sch.my_table")
        assert result is None

    @patch("benchmarks_api.db")
    def test_single_table_with_probe(self, mock_db):
        """One table with probe data → returns probe_time_ms."""
        mock_db.fetch_one.side_effect = [
            {"storage_location": "s3://bucket/table"},  # metadata cache
            {"probe_time_ms": 42.5},  # probe
        ]
        result = benchmarks_api._lookup_io_latency_ms("SELECT * FROM cat.sch.my_table")
        assert result == 42.5

    @patch("benchmarks_api.db")
    def test_multiple_tables_returns_max(self, mock_db):
        """Multiple tables → returns worst-case (max) probe_time_ms."""
        mock_db.fetch_one.side_effect = [
            {"storage_location": "s3://bucket/t1"},  # meta for t1
            {"probe_time_ms": 10.0},  # probe for t1
            {"storage_location": "s3://bucket/t2"},  # meta for t2
            {"probe_time_ms": 75.0},  # probe for t2
        ]
        result = benchmarks_api._lookup_io_latency_ms(
            "SELECT * FROM cat.sch.t1 JOIN cat.sch.t2 ON t1.id = t2.id"
        )
        assert result == 75.0

    @patch("benchmarks_api.db")
    def test_mixed_tables_some_without_probes(self, mock_db):
        """Two tables, one has probe, one doesn't → returns the one that has it."""
        mock_db.fetch_one.side_effect = [
            {"storage_location": "s3://bucket/t1"},  # meta for t1
            None,  # no probe for t1
            {"storage_location": "s3://bucket/t2"},  # meta for t2
            {"probe_time_ms": 30.0},  # probe for t2
        ]
        result = benchmarks_api._lookup_io_latency_ms(
            "SELECT * FROM cat.sch.t1 JOIN cat.sch.t2 ON t1.id = t2.id"
        )
        assert result == 30.0


# ---------------------------------------------------------------------------
# _get_or_create_definition unit tests
# ---------------------------------------------------------------------------


class TestGetOrCreateDefinition:
    """_get_or_create_definition — upsert logic."""

    @patch("benchmarks_api.db.fetch_one")
    def test_existing_returned(self, mock_one):
        """If definition exists, return it without INSERT."""
        existing = _definition_row(id=5, collection_id=1, engine_id="duckdb-1")
        mock_one.return_value = existing
        result = benchmarks_api._get_or_create_definition(1, "duckdb-1")
        assert result["id"] == 5
        # Only one SELECT, no INSERT
        assert mock_one.call_count == 1

    @patch("benchmarks_api.db.fetch_one")
    def test_created_when_missing(self, mock_one):
        """If no definition, INSERT and return new row."""
        new_row = _definition_row(id=10, collection_id=2, engine_id="duckdb-2")
        mock_one.side_effect = [None, new_row]
        result = benchmarks_api._get_or_create_definition(2, "duckdb-2")
        assert result["id"] == 10
        # First call: SELECT (miss), second: INSERT RETURNING
        assert mock_one.call_count == 2
