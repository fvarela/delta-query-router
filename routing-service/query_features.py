"""Pre-computed query features for ML training.

Stores AST features (from query_analyzer) and table metadata snapshots
alongside collection queries.  Features are computed eagerly on query insert
so the ML trainer can read them directly from the DB without re-parsing.

Public API:
    compute_and_store(query_id, sql_text) -> dict | None
        Parse SQL, store AST features, return the query_features row.
    compute_and_store_batch(rows) -> int
        Batch version — process [(query_id, sql_text), ...].
    update_table_metadata(query_ids, table_metadata) -> int
        Snapshot table sizes from catalog at benchmark time.
    backfill_all() -> dict
        Compute features for all queries missing them.
"""

from __future__ import annotations

import logging

import db
import query_analyzer

logger = logging.getLogger("routing-service.query_features")


def compute_and_store(query_id: int, sql_text: str) -> dict | None:
    """Parse SQL via query_analyzer and upsert AST features for a query.

    Returns the query_features row dict, or None if parsing failed.
    """
    analysis = query_analyzer.analyze_query(sql_text)
    if analysis.error is not None:
        logger.warning(
            "Cannot compute features for query %d: %s", query_id, analysis.error
        )
        return None

    return db.fetch_one(
        """
        INSERT INTO query_features (
            query_id, statement_type, tables,
            num_tables, num_joins, num_aggregations, num_subqueries,
            has_group_by, has_order_by, has_limit, has_window_functions,
            num_columns_selected, complexity_score
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (query_id) DO UPDATE SET
            statement_type = EXCLUDED.statement_type,
            tables = EXCLUDED.tables,
            num_tables = EXCLUDED.num_tables,
            num_joins = EXCLUDED.num_joins,
            num_aggregations = EXCLUDED.num_aggregations,
            num_subqueries = EXCLUDED.num_subqueries,
            has_group_by = EXCLUDED.has_group_by,
            has_order_by = EXCLUDED.has_order_by,
            has_limit = EXCLUDED.has_limit,
            has_window_functions = EXCLUDED.has_window_functions,
            num_columns_selected = EXCLUDED.num_columns_selected,
            complexity_score = EXCLUDED.complexity_score,
            updated_at = NOW()
        RETURNING *
        """,
        (
            query_id,
            analysis.statement_type,
            analysis.tables,
            analysis.num_tables,
            analysis.num_joins,
            analysis.num_aggregations,
            analysis.num_subqueries,
            analysis.has_group_by,
            analysis.has_order_by,
            analysis.has_limit,
            analysis.has_window_functions,
            analysis.num_columns_selected,
            analysis.complexity_score,
        ),
    )


def compute_and_store_batch(rows: list[tuple[int, str]]) -> int:
    """Compute and store features for a batch of (query_id, sql_text) pairs.

    Returns the number of successfully stored features.
    """
    stored = 0
    for query_id, sql_text in rows:
        result = compute_and_store(query_id, sql_text)
        if result is not None:
            stored += 1
    return stored


def update_table_metadata(
    query_ids: list[int],
    table_metadata: dict[str, int | None],
) -> int:
    """Snapshot table sizes for the given queries.

    Args:
        query_ids: Query IDs whose features should be updated.
        table_metadata: Map of table_name -> size_bytes (from catalog_service).

    Computes max_table_size_bytes and total_data_bytes per query by looking
    up its stored ``tables`` array against the provided metadata.

    Returns the number of rows updated.
    """
    if not query_ids or not table_metadata:
        return 0

    # Fetch the tables array for each query
    placeholders = ",".join(["%s"] * len(query_ids))
    features = db.fetch_all(
        f"SELECT query_id, tables FROM query_features WHERE query_id IN ({placeholders})",
        tuple(query_ids),
    )

    updated = 0
    for row in features:
        tables = row["tables"] or []
        sizes = [table_metadata.get(t) or 0 for t in tables]
        max_size = max(sizes) if sizes else None
        total_size = sum(sizes) if sizes else None

        db.execute(
            """
            UPDATE query_features
            SET max_table_size_bytes = %s,
                total_data_bytes = %s,
                metadata_snapshot_at = NOW(),
                updated_at = NOW()
            WHERE query_id = %s
            """,
            (max_size, total_size, row["query_id"]),
        )
        updated += 1

    return updated


def backfill_all() -> dict:
    """Compute features for all collection_queries missing a query_features row.

    Returns {"total": N, "computed": M, "skipped": S}.
    """
    missing = db.fetch_all(
        """
        SELECT cq.id AS query_id, cq.query_text
        FROM collection_queries cq
        LEFT JOIN query_features qf ON qf.query_id = cq.id
        WHERE qf.id IS NULL
        """
    )

    computed = 0
    skipped = 0
    for row in missing:
        result = compute_and_store(row["query_id"], row["query_text"])
        if result is not None:
            computed += 1
        else:
            skipped += 1

    logger.info(
        "Backfill complete: %d total, %d computed, %d skipped",
        len(missing),
        computed,
        skipped,
    )
    return {"total": len(missing), "computed": computed, "skipped": skipped}
