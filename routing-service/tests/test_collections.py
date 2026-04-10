"""Tests for collections CRUD endpoints (task 36)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import auth
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header():
    token = "test-token-collections"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _collection_row(id=1, name="Test Collection", description=None, **overrides):
    base = {
        "id": id,
        "name": name,
        "description": description,
        "created_at": "2026-04-01T00:00:00+00:00",
        "updated_at": "2026-04-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _query_row(
    id=1, collection_id=1, query_text="SELECT 1", sequence_number=1, **overrides
):
    base = {
        "id": id,
        "collection_id": collection_id,
        "query_text": query_text,
        "sequence_number": sequence_number,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


class TestAuthRequired:
    def test_list_requires_auth(self):
        resp = client.get("/api/collections")
        assert resp.status_code == 401

    def test_get_requires_auth(self):
        resp = client.get("/api/collections/1")
        assert resp.status_code == 401

    def test_create_requires_auth(self):
        resp = client.post("/api/collections", json={"name": "x"})
        assert resp.status_code == 401

    def test_update_requires_auth(self):
        resp = client.put("/api/collections/1", json={"name": "x"})
        assert resp.status_code == 401

    def test_delete_requires_auth(self):
        resp = client.delete("/api/collections/1")
        assert resp.status_code == 401

    def test_add_query_requires_auth(self):
        resp = client.post(
            "/api/collections/1/queries", json={"query_text": "SELECT 1"}
        )
        assert resp.status_code == 401

    def test_delete_query_requires_auth(self):
        resp = client.delete("/api/collections/1/queries/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List collections
# ---------------------------------------------------------------------------


class TestListCollections:
    @patch("collections_api.db.fetch_all")
    def test_empty(self, mock_fetch):
        mock_fetch.return_value = []
        resp = client.get("/api/collections", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("collections_api.db.fetch_all")
    def test_returns_collections_with_query_count(self, mock_fetch):
        mock_fetch.return_value = [
            {**_collection_row(id=1, name="A"), "query_count": 3},
            {**_collection_row(id=2, name="B"), "query_count": 0},
        ]
        resp = client.get("/api/collections", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[0]["query_count"] == 3
        assert data[1]["query_count"] == 0

    @patch("collections_api.db.fetch_all")
    def test_filter_by_tag(self, mock_fetch):
        mock_fetch.return_value = []
        resp = client.get("/api/collections?tag=tpcds", headers=_auth_header())
        assert resp.status_code == 200
        sql = mock_fetch.call_args[0][0]
        assert "tag" in sql


# ---------------------------------------------------------------------------
# Get collection
# ---------------------------------------------------------------------------


class TestGetCollection:
    @patch("collections_api.db.fetch_all")
    @patch("collections_api.db.fetch_one")
    def test_returns_collection_with_queries(self, mock_one, mock_all):
        mock_one.return_value = _collection_row(id=1, name="My Coll")
        mock_all.return_value = [
            _query_row(id=1, sequence_number=1, query_text="SELECT 1"),
            _query_row(id=2, sequence_number=2, query_text="SELECT 2"),
        ]
        resp = client.get("/api/collections/1", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Coll"
        assert len(data["queries"]) == 2
        assert data["queries"][0]["query_text"] == "SELECT 1"

    @patch("collections_api.db.fetch_one")
    def test_not_found(self, mock_one):
        mock_one.return_value = None
        resp = client.get("/api/collections/999", headers=_auth_header())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create collection
# ---------------------------------------------------------------------------


class TestCreateCollection:
    @patch("collections_api.db.fetch_one")
    def test_creates_collection(self, mock_one):
        mock_one.return_value = _collection_row(
            id=1, name="New", description="desc", tag="user"
        )
        resp = client.post(
            "/api/collections",
            json={"name": "New", "description": "desc"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "New"
        assert resp.json()["description"] == "desc"
        # Verify the SQL was called with correct params
        sql, params = mock_one.call_args[0]
        assert "INSERT INTO collections" in sql
        assert params == ("New", "desc", "user")

    @patch("collections_api.db.fetch_one")
    def test_creates_without_description(self, mock_one):
        mock_one.return_value = _collection_row(id=2, name="No Desc", tag="user")
        resp = client.post(
            "/api/collections",
            json={"name": "No Desc"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        sql, params = mock_one.call_args[0]
        assert params == ("No Desc", None, "user")

    @patch("collections_api.db.fetch_one")
    def test_creates_with_tpcds_tag(self, mock_one):
        mock_one.return_value = _collection_row(id=3, name="TPC-DS SF1", tag="tpcds")
        resp = client.post(
            "/api/collections",
            json={"name": "TPC-DS SF1", "tag": "tpcds"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        sql, params = mock_one.call_args[0]
        assert params == ("TPC-DS SF1", None, "tpcds")

    def test_creates_with_invalid_tag(self):
        resp = client.post(
            "/api/collections",
            json={"name": "Bad", "tag": "invalid"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "tag" in resp.json()["detail"].lower()

    def test_missing_name_returns_422(self):
        resp = client.post(
            "/api/collections",
            json={"description": "no name"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Update collection
# ---------------------------------------------------------------------------


class TestUpdateCollection:
    @patch("collections_api.db.fetch_one")
    def test_updates_name(self, mock_one):
        # First call: check existence. Second call: UPDATE RETURNING.
        mock_one.side_effect = [
            _collection_row(id=1, name="Old"),
            _collection_row(id=1, name="New"),
        ]
        resp = client.put(
            "/api/collections/1",
            json={"name": "New"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    @patch("collections_api.db.fetch_one")
    def test_not_found(self, mock_one):
        mock_one.return_value = None
        resp = client.put(
            "/api/collections/999",
            json={"name": "x"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    @patch("collections_api.db.fetch_one")
    def test_empty_body_returns_existing(self, mock_one):
        existing = _collection_row(id=1, name="Same")
        mock_one.return_value = existing
        resp = client.put(
            "/api/collections/1",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Same"

    @patch("collections_api.db.fetch_one")
    def test_tpcds_collection_returns_403(self, mock_one):
        mock_one.return_value = _collection_row(id=1, name="TPC-DS", tag="tpcds")
        resp = client.put(
            "/api/collections/1",
            json={"name": "Renamed"},
            headers=_auth_header(),
        )
        assert resp.status_code == 403
        assert "TPC-DS" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Delete collection
# ---------------------------------------------------------------------------


class TestDeleteCollection:
    @patch("collections_api.db.execute")
    @patch("collections_api.db.fetch_one")
    def test_deletes(self, mock_one, mock_exec):
        mock_one.return_value = _collection_row(id=1)
        resp = client.delete("/api/collections/1", headers=_auth_header())
        assert resp.status_code == 204
        sql, params = mock_exec.call_args[0]
        assert "DELETE FROM collections" in sql
        assert params == (1,)

    @patch("collections_api.db.fetch_one")
    def test_not_found(self, mock_one):
        mock_one.return_value = None
        resp = client.delete("/api/collections/999", headers=_auth_header())
        assert resp.status_code == 404

    @patch("collections_api.db.fetch_one")
    def test_tpcds_collection_returns_403(self, mock_one):
        mock_one.return_value = _collection_row(id=1, name="TPC-DS", tag="tpcds")
        resp = client.delete("/api/collections/1", headers=_auth_header())
        assert resp.status_code == 403
        assert "TPC-DS" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Add query
# ---------------------------------------------------------------------------


class TestAddQuery:
    @patch("collections_api.db.fetch_one")
    def test_adds_with_explicit_sequence(self, mock_one):
        # First call: collection exists. Second call: INSERT RETURNING.
        mock_one.side_effect = [
            _collection_row(id=1),
            _query_row(
                id=10, collection_id=1, query_text="SELECT 42", sequence_number=5
            ),
        ]
        resp = client.post(
            "/api/collections/1/queries",
            json={"query_text": "SELECT 42", "sequence_number": 5},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["query_text"] == "SELECT 42"
        assert resp.json()["sequence_number"] == 5

    @patch("collections_api.db.fetch_one")
    def test_auto_sequence_number(self, mock_one):
        # First call: collection exists. Second call: MAX seq. Third call: INSERT.
        mock_one.side_effect = [
            _collection_row(id=1),
            {"next_seq": 3},
            _query_row(
                id=11, collection_id=1, query_text="SELECT 99", sequence_number=3
            ),
        ]
        resp = client.post(
            "/api/collections/1/queries",
            json={"query_text": "SELECT 99"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        assert resp.json()["sequence_number"] == 3

    @patch("collections_api.db.fetch_one")
    def test_collection_not_found(self, mock_one):
        mock_one.return_value = None
        resp = client.post(
            "/api/collections/999/queries",
            json={"query_text": "SELECT 1"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_missing_query_text_returns_422(self):
        resp = client.post(
            "/api/collections/1/queries",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    @patch("collections_api.db.fetch_one")
    def test_tpcds_collection_returns_403(self, mock_one):
        """Cannot add queries to a TPC-DS collection."""
        mock_one.return_value = _collection_row(id=1, name="TPC-DS", tag="tpcds")
        resp = client.post(
            "/api/collections/1/queries",
            json={"query_text": "SELECT 1"},
            headers=_auth_header(),
        )
        assert resp.status_code == 403
        assert "TPC-DS" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Delete query
# ---------------------------------------------------------------------------


class TestDeleteQuery:
    @patch("collections_api.db.execute")
    @patch("collections_api.db.fetch_one")
    def test_deletes(self, mock_one, mock_exec):
        # First call: collection lookup, second call: query lookup
        mock_one.side_effect = [
            _collection_row(id=1, tag="user"),
            _query_row(id=5, collection_id=1),
        ]
        resp = client.delete("/api/collections/1/queries/5", headers=_auth_header())
        assert resp.status_code == 204
        sql, params = mock_exec.call_args[0]
        assert "DELETE FROM collection_queries" in sql
        assert params == (5,)

    @patch("collections_api.db.fetch_one")
    def test_not_found(self, mock_one):
        # Collection exists but query doesn't
        mock_one.side_effect = [_collection_row(id=1, tag="user"), None]
        resp = client.delete("/api/collections/1/queries/999", headers=_auth_header())
        assert resp.status_code == 404

    @patch("collections_api.db.fetch_one")
    def test_wrong_collection_not_found(self, mock_one):
        """Query exists but belongs to a different collection."""
        mock_one.return_value = None  # collection not found
        resp = client.delete("/api/collections/99/queries/5", headers=_auth_header())
        assert resp.status_code == 404

    @patch("collections_api.db.fetch_one")
    def test_tpcds_collection_returns_403(self, mock_one):
        """Cannot delete queries from a TPC-DS collection."""
        mock_one.return_value = _collection_row(id=1, name="TPC-DS", tag="tpcds")
        resp = client.delete("/api/collections/1/queries/5", headers=_auth_header())
        assert resp.status_code == 403
        assert "TPC-DS" in resp.json()["detail"]
