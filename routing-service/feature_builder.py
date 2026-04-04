"""Feature vector builder for ML model training and inference.

Takes a QueryAnalysis (from query_analyzer) and table metadata (from catalog_service)
and produces a flat numeric feature vector suitable for scikit-learn models.

Features per ODQ-3:
  Query features:  num_tables, num_joins, num_aggregations, num_subqueries,
                   has_group_by, has_order_by, has_limit, has_window_functions,
                   num_columns_selected, complexity_score
  Table features:  max_table_size_bytes, total_data_bytes
  Engine features: engine_type (0=duckdb, 1=databricks), cost_tier
"""

from __future__ import annotations

from query_analyzer import QueryAnalysis
from catalog_service import TableMetadata

# Ordered feature names — must stay consistent between training and inference.
FEATURE_NAMES: list[str] = [
    # Query features (from QueryAnalysis)
    "num_tables",
    "num_joins",
    "num_aggregations",
    "num_subqueries",
    "has_group_by",
    "has_order_by",
    "has_limit",
    "has_window_functions",
    "num_columns_selected",
    "complexity_score",
    # Table features (from TableMetadata)
    "max_table_size_bytes",
    "total_data_bytes",
    # Engine features (passed separately)
    "engine_type",
    "cost_tier",
]

_ENGINE_TYPE_MAP: dict[str, int] = {
    "duckdb": 0,
    "databricks": 1,
}


def build_feature_vector(
    analysis: QueryAnalysis,
    table_metadata: dict[str, TableMetadata],
    engine_type: str,
    cost_tier: int,
) -> dict[str, float]:
    """Build an ordered feature dict from query analysis + metadata + engine info.

    Args:
        analysis: Parsed query analysis from query_analyzer.
        table_metadata: Map of table_name -> TableMetadata (may be empty).
        engine_type: 'duckdb' or 'databricks'.
        cost_tier: Integer cost tier from engines table (1-10).

    Returns:
        Ordered dict with float values, keys matching FEATURE_NAMES.
    """
    # Extract table sizes, treating None as 0
    sizes = [(tm.size_bytes or 0) for tm in table_metadata.values()]
    max_table_size_bytes = max(sizes) if sizes else 0
    total_data_bytes = sum(sizes)

    return {
        "num_tables": float(analysis.num_tables),
        "num_joins": float(analysis.num_joins),
        "num_aggregations": float(analysis.num_aggregations),
        "num_subqueries": float(analysis.num_subqueries),
        "has_group_by": 1.0 if analysis.has_group_by else 0.0,
        "has_order_by": 1.0 if analysis.has_order_by else 0.0,
        "has_limit": 1.0 if analysis.has_limit else 0.0,
        "has_window_functions": 1.0 if analysis.has_window_functions else 0.0,
        "num_columns_selected": float(analysis.num_columns_selected),
        "complexity_score": float(analysis.complexity_score),
        "max_table_size_bytes": float(max_table_size_bytes),
        "total_data_bytes": float(total_data_bytes),
        "engine_type": float(_ENGINE_TYPE_MAP.get(engine_type, 0)),
        "cost_tier": float(cost_tier),
    }


def feature_dict_to_array(features: dict[str, float]) -> list[float]:
    """Convert a feature dict to an ordered list matching FEATURE_NAMES.

    Used as input to sklearn model.predict().
    """
    return [features[name] for name in FEATURE_NAMES]


def get_feature_names() -> list[str]:
    """Return the ordered feature name list (for model introspection)."""
    return list(FEATURE_NAMES)
