"""Tests for benchmarks_api.py — benchmark execution + CRUD."""

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


def _benchmark_row(id=1, collection_id=1, status="warming_up"):
    return {
        "id": id,
        "collection_id": collection_id,
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

        # fetch_one calls: collection, engine, INSERT benchmark
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _benchmark_row(id=42),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 42
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
        # Status transitions are embedded in SQL strings
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
        """Warmup failure → benchmark marked 'failed'."""
        mock_one.side_effect = [
            _collection_row(),
            _engine_row(),
            _benchmark_row(id=10),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 10
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
        """One query fails → error recorded, benchmark still completes."""
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
            _benchmark_row(id=7),
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
        """2 engines × 1 query = 2 warmups + 2 results."""
        mock_run_query.return_value = {"execution_time_ms": 8.0, "error_message": None}

        mock_one.side_effect = [
            _collection_row(),
            _engine_row(id="duckdb-1"),
            _engine_row(id="duckdb-2"),
            _benchmark_row(id=99),
        ]
        mock_all.return_value = [_query_row()]

        resp = client.post(
            "/api/benchmarks",
            json={"collection_id": 1, "engine_ids": ["duckdb-1", "duckdb-2"]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        assert resp.json()["status"] == "complete"

        # 2 warmup calls
        assert mock_warmup.call_count == 2
        # 2 query executions
        assert mock_run_query.call_count == 2


# ---------------------------------------------------------------------------
# GET /api/benchmarks — list
# ---------------------------------------------------------------------------


class TestListBenchmarks:
    """GET /api/benchmarks — list benchmarks."""

    @patch("benchmarks_api.db.fetch_all")
    def test_list_all(self, mock_all):
        mock_all.return_value = [
            {
                "id": 1,
                "collection_id": 1,
                "collection_name": "C1",
                "status": "complete",
                "engine_count": 2,
                "created_at": _NOW,
                "updated_at": _NOW,
            },
        ]
        resp = client.get("/api/benchmarks", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["collection_name"] == "C1"

    @patch("benchmarks_api.db.fetch_all")
    def test_list_filtered(self, mock_all):
        mock_all.return_value = []
        resp = client.get("/api/benchmarks?collection_id=5", headers=_auth_header())
        assert resp.status_code == 200
        # Verify filter was passed
        sql = mock_all.call_args[0][0]
        assert "collection_id" in sql

    def test_requires_auth(self):
        resp = client.get("/api/benchmarks")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/benchmarks/{id} — detail
# ---------------------------------------------------------------------------


class TestGetBenchmark:
    """GET /api/benchmarks/{id} — full benchmark detail."""

    @patch("benchmarks_api.db.fetch_all")
    @patch("benchmarks_api.db.fetch_one")
    def test_get_detail(self, mock_one, mock_all):
        mock_one.return_value = {
            "id": 1,
            "collection_id": 1,
            "collection_name": "Test",
            "status": "complete",
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        mock_all.side_effect = [
            # warmups
            [
                {
                    "id": 1,
                    "benchmark_id": 1,
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
                    "benchmark_id": 1,
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

        resp = client.get("/api/benchmarks/1", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["collection_name"] == "Test"
        assert data["status"] == "complete"
        assert len(data["warmups"]) == 1
        assert data["warmups"][0]["cold_start_time_ms"] == 50.0
        assert len(data["results"]) == 1
        assert data["results"][0]["execution_time_ms"] == 12.0

    @patch("benchmarks_api.db.fetch_one", return_value=None)
    def test_not_found(self, mock_one):
        resp = client.get("/api/benchmarks/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/benchmarks/{id}
# ---------------------------------------------------------------------------


class TestDeleteBenchmark:
    """DELETE /api/benchmarks/{id} — cascade delete."""

    @patch("benchmarks_api.db.execute")
    @patch("benchmarks_api.db.fetch_one")
    def test_delete_existing(self, mock_one, mock_exec):
        mock_one.return_value = _benchmark_row(id=5)
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
