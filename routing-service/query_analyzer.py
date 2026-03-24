import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

logger = logging.getLogger("routing-service.query_analyzer")

# --- Complexity weight constants (tunable) ---
W_JOIN = 3
W_AGGREGATION = 2
W_SUBQUERY = 5
W_GROUP_BY = 1
W_ORDER_BY = 0.5
W_WINDOW_FUNCTION = 4
W_EXTRA_TABLE = 1  # per table beyond the first


@dataclass
class QueryAnalysis:
    statement_type: str
    tables: list[str]
    num_tables: int
    num_joins: int
    num_aggregations: int
    num_subqueries: int
    has_group_by: bool
    has_order_by: bool
    has_limit: bool
    has_window_functions: bool
    num_columns_selected: int
    complexity_score: float
    error: str | None = None


def _default_analysis(error: str) -> QueryAnalysis:
    """Return a default analysis for unparseable or empty SQL."""
    return QueryAnalysis(
        statement_type="OTHER",
        tables=[],
        num_tables=0,
        num_joins=0,
        num_aggregations=0,
        num_subqueries=0,
        has_group_by=False,
        has_order_by=False,
        has_limit=False,
        has_window_functions=False,
        num_columns_selected=0,
        complexity_score=0.0,
        error=error,
    )


def analyze_query(sql: str) -> QueryAnalysis:
    """Parse SQL and return analysis with complexity score."""
    # 0. Empty input check
    if not sql or not sql.strip():
        return _default_analysis("empty SQL")

    # 1. Parse
    try:
        parsed = sqlglot.parse(sql)
    except sqlglot.errors.SqlglotError:
        logger.warning("Failed to parse SQL: %s", sql[:200])
        return _default_analysis("parse error")

    if not parsed or parsed[0] is None:
        return _default_analysis("parse error")

    # Use the first statement only
    tree = parsed[0]

    # 2. Statement type
    if isinstance(tree, exp.Select):
        statement_type = "SELECT"
    elif isinstance(tree, exp.Insert):
        statement_type = "INSERT"
    elif isinstance(tree, exp.Create):
        statement_type = "CREATE"
    else:
        statement_type = "OTHER"

    # 3. Extract tables - find all Table nodes, build qualified names
    tables = []
    for table in tree.find_all(exp.Table):
        parts = []
        if table.catalog:
            parts.append(table.catalog)
        if table.db:
            parts.append(table.db)
        if table.name:
            parts.append(table.name)
        if parts:
            tables.append(".".join(parts))
    # Deduplicate while preserving order
    seen = set()
    unique_tables = []
    for t in tables:
        if t not in seen:
            seen.add(t)
            unique_tables.append(t)
    tables = unique_tables

    # 4. Count features by walking the AST
    num_joins = len(list(tree.find_all(exp.Join)))
    num_aggregations = len(list(tree.find_all(exp.AggFunc)))
    num_subqueries = len(list(tree.find_all(exp.Subquery)))
    has_group_by = tree.find(exp.Group) is not None
    has_order_by = tree.find(exp.Order) is not None
    has_limit = tree.find(exp.Limit) is not None
    has_window_functions = tree.find(exp.Window) is not None

    # 5. Count selected columns (only meaningful for SELECT)
    num_columns_selected = 0
    if isinstance(tree, exp.Select):
        num_columns_selected = len(tree.expressions)

    # 6. Compute complexity score
    complexity_score = (
        num_joins * W_JOIN
        + num_aggregations * W_AGGREGATION
        + num_subqueries * W_SUBQUERY
        + has_group_by * W_GROUP_BY
        + has_order_by * W_ORDER_BY
        + has_window_functions * W_WINDOW_FUNCTION
        + max(0, len(tables) - 1) * W_EXTRA_TABLE
    )

    return QueryAnalysis(
        statement_type=statement_type,
        tables=tables,
        num_tables=len(tables),
        num_joins=num_joins,
        num_aggregations=num_aggregations,
        num_subqueries=num_subqueries,
        has_group_by=has_group_by,
        has_order_by=has_order_by,
        has_limit=has_limit,
        has_window_functions=has_window_functions,
        num_columns_selected=num_columns_selected,
        complexity_score=complexity_score,
    )
