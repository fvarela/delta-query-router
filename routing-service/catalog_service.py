"""Unity Catalog metadata fetching with PostgreSQL-backed caching."""

import logging
from dataclasses import dataclass

import db

logger = logging.getLogger("routing-service.catalog")

# Cache TTL in seconds (uniform for all fields - see PROJECT.md)
CACHE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class TableMetadata:
    """Metadata for a single Unity Catalog table, used by the routing engine."""

    full_name: str
    table_type: str  # MANAGED, EXTERNAL, VIEW, FOREIGN, UNKNOWN
    data_source_format: str  # DELTA, ICEBERG, SQLSERVER, etc. or UNKNOWN
    storage_location: str | None
    size_bytes: int | None
    has_rls: bool
    has_column_masking: bool
    external_engine_read_support: bool
    cached: bool


def _unknown_metadata(full_name: str) -> TableMetadata:
    """Conservative fallback - routes to Databricks (external_engine_read_support=False)."""
    return TableMetadata(
        full_name=full_name,
        table_type="UNKNOWN",
        data_source_format="UNKNOWN",
        storage_location=None,
        size_bytes=None,
        has_rls=False,
        has_column_masking=False,
        external_engine_read_support=False,
        cached=False,
    )


def _get_from_cache(full_name: str) -> TableMetadata | None:
    """Check PostgreSQL cache. Returns TableMetadata if valid (within TTL), else None."""
    row = db.fetch_one(
        """
        SELECT table_name, table_type, data_source_format, storage_location, 
                size_bytes, has_rls, has_column_masking, external_engine_read_support, cached_at, ttl_seconds
        FROM table_metadata_cache
        WHERE table_name = %s
        AND cached_at + (ttl_seconds || ' seconds')::INTERVAL > NOW()
        """,
        (full_name,),
    )
    if row is None:
        return None
    return TableMetadata(
        full_name=row["table_name"],
        table_type=row["table_type"],
        data_source_format=row["data_source_format"] or "UNKNOWN",
        storage_location=row["storage_location"],
        size_bytes=row["size_bytes"],
        has_rls=row["has_rls"],
        has_column_masking=row["has_column_masking"],
        external_engine_read_support=row["external_engine_read_support"],
        cached=True,
    )


def _write_to_cache(metadata: TableMetadata) -> None:
    """Upsert table metadata into cache."""
    parts = metadata.full_name.split(".")
    catalog = parts[0] if len(parts) >= 1 else None
    schema_name = parts[1] if len(parts) >= 2 else None
    db.execute(
        """
        INSERT INTO table_metadata_cache (table_name, catalog, schema_name, table_type, data_source_format, storage_location,
                size_bytes, has_rls, has_column_masking, external_engine_read_support, cached_at, ttl_seconds)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        ON CONFLICT (table_name) DO UPDATE SET
            table_type = EXCLUDED.table_type,
            data_source_format = EXCLUDED.data_source_format,
            storage_location = EXCLUDED.storage_location,
            size_bytes = EXCLUDED.size_bytes,
            has_rls = EXCLUDED.has_rls,
            has_column_masking = EXCLUDED.has_column_masking,
            external_engine_read_support = EXCLUDED.external_engine_read_support,
            cached_at = NOW(),
            ttl_seconds = EXCLUDED.ttl_seconds
        """,
        (
            metadata.full_name,
            catalog,
            schema_name,
            metadata.table_type,
            metadata.data_source_format,
            metadata.storage_location,
            metadata.size_bytes,
            metadata.has_rls,
            metadata.has_column_masking,
            metadata.external_engine_read_support,
            CACHE_TTL_SECONDS,
        ),
    )


def _fetch_from_catalog(full_name: str, workspace_client) -> TableMetadata:
    """Fetch table metadata from Unity Catalog via databricks-sdk."""
    table_info = workspace_client.tables.get(
        full_name, include_manifest_capabilities=True
    )

    # table_type and data_source_format are enums - extract .value
    table_type = table_info.table_type.value if table_info.table_type else "UNKNOWN"
    data_source_format = (
        table_info.data_source_format.value
        if table_info.data_source_format
        else "UNKNOWN"
    )

    # Governance: row-level security
    has_rls = table_info.row_filter is not None

    # Governance: column masking (per-column on ColumnInfo.mask)
    has_column_masking = any(col.mask is not None for col in (table_info.columns or []))

    # External engine read support from manifest capabilities
    capabilities = []
    if (
        table_info.securable_kind_manifest
        and table_info.securable_kind_manifest.capabilities
    ):
        capabilities = table_info.securable_kind_manifest.capabilities
    external_engine_read_support = (
        "HAS_DIRECT_EXTERNAL_ENGINE_READ_SUPPORT" in capabilities
    )

    # Size from table properties (Spark statistics)
    size_bytes = None
    if table_info.properties:
        size_str = table_info.properties.get("spark.sql.statistics.totalSize")
        if size_str is not None:
            try:
                size_bytes = int(size_str)
            except ValueError:
                pass

    return TableMetadata(
        full_name=full_name,
        table_type=table_type,
        data_source_format=data_source_format,
        storage_location=table_info.storage_location,
        size_bytes=size_bytes,
        has_rls=has_rls,
        has_column_masking=has_column_masking,
        external_engine_read_support=external_engine_read_support,
        cached=False,
    )


def get_table_metadata(full_name: str, workspace_client) -> TableMetadata:
    """Get metadata for a single table. Checks cache first, then Unity Catalog.

    Returns UNKNOWN metadata (conservative, routes to Databricks) when:
    - workspace_client is None (no Databricks connection)
    - SDK call fails (table not found, permissions, network error)
    - Cache read fails (database unavailable)
    """
    # Try cache first
    try:
        cached = _get_from_cache(full_name)
        if cached is not None:
            logger.debug("Cache hit for %s", full_name)
            return cached
    except Exception:
        logger.warning(
            "Cache read failed for %s, falling back to SDK",
            full_name,
            exc_info=True,
        )

    # No workspace client — return conservative defaults
    if workspace_client is None:
        logger.info("No workspace client, returning UNKNOWN metadata for %s", full_name)
        return _unknown_metadata(full_name)

    # Fetch from Unity Catalog
    try:
        metadata = _fetch_from_catalog(full_name, workspace_client)
    except Exception:
        logger.warning(
            "SDK fetch failed for %s, returning UNKNOWN metadata",
            full_name,
            exc_info=True,
        )
        return _unknown_metadata(full_name)

    # Write to cache (best-effort)
    try:
        _write_to_cache(metadata)
        logger.debug("Cached metadata for %s", full_name)
    except Exception:
        logger.warning("Cache write failed for %s", full_name, exc_info=True)
    return metadata


def get_tables_metadata(
    table_names: list[str], workspace_client
) -> dict[str, TableMetadata]:
    """Batch lookup for all tables referenced in a query.

    Returns a dict keyed by full table name.
    """
    result = {}
    for name in table_names:
        result[name] = get_table_metadata(name, workspace_client)
    return result
