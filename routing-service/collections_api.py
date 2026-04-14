"""Collections CRUD — query collections and their queries."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import db
import query_features

logger = logging.getLogger("routing-service.collections")

router = APIRouter(prefix="/api/collections", tags=["collections"])


# --- Pydantic models ---


class CreateCollection(BaseModel):
    name: str
    description: str | None = None
    tag: str = "user"


class UpdateCollection(BaseModel):
    name: str | None = None
    description: str | None = None


class AddQuery(BaseModel):
    query_text: str
    sequence_number: int | None = None


class UpdateQuery(BaseModel):
    query_text: str | None = None
    sequence_number: int | None = None


# --- Collection endpoints ---


def _check_tpcds_readonly(collection: dict, action: str = "modify"):
    """Raise 403 if collection is TPC-DS (read-only)."""
    if collection.get("tag") == "tpcds":
        raise HTTPException(
            status_code=403,
            detail=f"Cannot {action} TPC-DS collection (read-only)",
        )


@router.get("")
async def list_collections(tag: str | None = None):
    """List all collections with query count, optionally filtered by tag."""
    if tag is not None:
        return db.fetch_all(
            """
            SELECT c.*, COUNT(q.id) AS query_count
            FROM collections c
            LEFT JOIN collection_queries q ON q.collection_id = c.id
            WHERE c.tag = %s
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """,
            (tag,),
        )
    return db.fetch_all(
        """
        SELECT c.*, COUNT(q.id) AS query_count
        FROM collections c
        LEFT JOIN collection_queries q ON q.collection_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
        """
    )


@router.get("/{collection_id}")
async def get_collection(collection_id: int):
    """Get a collection with its queries."""
    collection = db.fetch_one(
        "SELECT * FROM collections WHERE id = %s", (collection_id,)
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    queries = db.fetch_all(
        "SELECT * FROM collection_queries WHERE collection_id = %s ORDER BY sequence_number",
        (collection_id,),
    )
    return {**collection, "queries": queries}


@router.post("", status_code=201)
async def create_collection(body: CreateCollection):
    """Create a new collection."""
    if body.tag not in ("user", "tpcds"):
        raise HTTPException(status_code=400, detail="tag must be 'user' or 'tpcds'")
    return db.fetch_one(
        "INSERT INTO collections (name, description, tag) VALUES (%s, %s, %s) RETURNING *",
        (body.name, body.description, body.tag),
    )


@router.put("/{collection_id}")
async def update_collection(collection_id: int, body: UpdateCollection):
    """Update a collection's name or description."""
    existing = db.fetch_one("SELECT * FROM collections WHERE id = %s", (collection_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")
    _check_tpcds_readonly(existing, "update")
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.description is not None:
        fields["description"] = body.description
    if not fields:
        return existing
    set_parts = [f"{k} = %s" for k in fields]
    set_parts.append("updated_at = NOW()")
    values = list(fields.values()) + [collection_id]
    return db.fetch_one(
        f"UPDATE collections SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
        tuple(values),
    )


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(collection_id: int):
    """Delete a collection and all its queries (CASCADE)."""
    existing = db.fetch_one("SELECT * FROM collections WHERE id = %s", (collection_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")
    _check_tpcds_readonly(existing, "delete")
    db.execute("DELETE FROM collections WHERE id = %s", (collection_id,))
    return Response(status_code=204)


# --- Query endpoints ---


@router.post("/{collection_id}/queries", status_code=201)
async def add_query(collection_id: int, body: AddQuery):
    """Add a query to a collection."""
    existing = db.fetch_one("SELECT * FROM collections WHERE id = %s", (collection_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")
    _check_tpcds_readonly(existing, "add queries to")
    if body.sequence_number is not None:
        seq = body.sequence_number
    else:
        result = db.fetch_one(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_seq "
            "FROM collection_queries WHERE collection_id = %s",
            (collection_id,),
        )
        seq = result["next_seq"]
    row = db.fetch_one(
        "INSERT INTO collection_queries (collection_id, query_text, sequence_number) "
        "VALUES (%s, %s, %s) RETURNING *",
        (collection_id, body.query_text, seq),
    )
    # Eagerly compute and store AST features for ML training
    query_features.compute_and_store(row["id"], body.query_text)
    return row


@router.delete("/{collection_id}/queries/{query_id}", status_code=204)
async def delete_query(collection_id: int, query_id: int):
    """Delete a query from a collection."""
    collection = db.fetch_one(
        "SELECT * FROM collections WHERE id = %s", (collection_id,)
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    _check_tpcds_readonly(collection, "delete queries from")
    existing = db.fetch_one(
        "SELECT * FROM collection_queries WHERE id = %s AND collection_id = %s",
        (query_id, collection_id),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Query not found")
    db.execute("DELETE FROM collection_queries WHERE id = %s", (query_id,))
    return Response(status_code=204)
