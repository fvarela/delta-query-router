"""Tests for tpcds_queries module — template completeness, rewriting, and parsing."""

import re

import pytest
import sqlglot

from tpcds_queries import (
    TPCDS_QUERIES,
    TPCDS_TABLES,
    get_queries,
    rewrite_query,
    validate_queries,
)


# ---- Template completeness ----


def test_all_99_templates_present():
    """All 99 TPC-DS queries are present with IDs 1-99."""
    assert len(TPCDS_QUERIES) == 99
    ids = [qid for qid, _ in TPCDS_QUERIES]
    assert ids == list(range(1, 100))


def test_25_tables_listed():
    """All 25 standard TPC-DS tables are listed."""
    assert len(TPCDS_TABLES) == 25
    expected = {
        "call_center",
        "catalog_page",
        "catalog_returns",
        "catalog_sales",
        "customer",
        "customer_address",
        "customer_demographics",
        "date_dim",
        "household_demographics",
        "income_band",
        "inventory",
        "item",
        "promotion",
        "reason",
        "ship_mode",
        "store",
        "store_returns",
        "store_sales",
        "time_dim",
        "warehouse",
        "web_page",
        "web_returns",
        "web_sales",
        "web_site",
        "dbgen_version",
    }
    assert set(TPCDS_TABLES) == expected


def test_templates_have_placeholders():
    """Every template contains at least one __CATALOG__.__SCHEMA__ placeholder."""
    for qid, tmpl in TPCDS_QUERIES:
        assert "__CATALOG__" in tmpl, f"Query {qid}: no __CATALOG__ placeholder"
        assert "__SCHEMA__" in tmpl, f"Query {qid}: no __SCHEMA__ placeholder"


def test_templates_are_non_empty_strings():
    """Every template is a non-empty string."""
    for qid, tmpl in TPCDS_QUERIES:
        assert isinstance(tmpl, str), f"Query {qid}: not a string"
        assert len(tmpl.strip()) > 0, f"Query {qid}: empty template"


# ---- Rewrite correctness ----


def test_rewrite_produces_three_part_names():
    """rewrite_query substitutes placeholders with catalog.schema.table."""
    sample_ids = [1, 5, 10, 50, 51, 99]
    for qid, tmpl in TPCDS_QUERIES:
        if qid not in sample_ids:
            continue
        rewritten = rewrite_query(tmpl, "mycat", "sf1")
        assert "__CATALOG__" not in rewritten, f"Q{qid}: __CATALOG__ remains"
        assert "__SCHEMA__" not in rewritten, f"Q{qid}: __SCHEMA__ remains"
        # Should contain at least one three-part name
        assert "mycat.sf1." in rewritten, f"Q{qid}: no three-part name found"


def test_rewrite_all_queries_no_leftover_placeholders():
    """After rewriting, no query contains leftover __CATALOG__ or __SCHEMA__."""
    for qid, sql in get_queries("cat", "sch"):
        assert "__CATALOG__" not in sql, f"Q{qid}: __CATALOG__ remains"
        assert "__SCHEMA__" not in sql, f"Q{qid}: __SCHEMA__ remains"


def test_rewrite_specific_table_names():
    """Rewritten queries contain expected three-part table names."""
    # Query 1 uses: store_returns, date_dim, store, customer
    q1_tmpl = next(t for qid, t in TPCDS_QUERIES if qid == 1)
    q1 = rewrite_query(q1_tmpl, "delta_router_tpcds", "sf1")
    assert "delta_router_tpcds.sf1.store_returns" in q1
    assert "delta_router_tpcds.sf1.date_dim" in q1
    assert "delta_router_tpcds.sf1.store" in q1
    assert "delta_router_tpcds.sf1.customer" in q1


# ---- Partial match prevention ----


def test_no_partial_matches_store_variants():
    """store, store_sales, store_returns are each replaced independently."""
    # Query 1 uses store_returns and store — verify no corruption
    q1_tmpl = next(t for qid, t in TPCDS_QUERIES if qid == 1)
    q1 = rewrite_query(q1_tmpl, "c", "s")
    assert "c.s.store_returns" in q1
    # No double-prefixed names
    assert "c.s.c.s." not in q1


def test_no_partial_matches_catalog_variants():
    """catalog_page, catalog_returns, catalog_sales are independent."""
    # Query 15 uses catalog_sales
    q15_tmpl = next(t for qid, t in TPCDS_QUERIES if qid == 15)
    q15 = rewrite_query(q15_tmpl, "x", "y")
    assert "x.y.catalog_sales" in q15
    assert "x.y.x.y." not in q15


def test_column_aliases_not_templatized():
    """Q51 uses web_sales/store_sales as column aliases — these must stay bare."""
    q51_tmpl = next(t for qid, t in TPCDS_QUERIES if qid == 51)
    q51 = rewrite_query(q51_tmpl, "mycat", "sf1")
    # The column alias pattern: "web.cume_sales AS web_sales"
    assert "cume_sales AS web_sales" in q51, "Q51: web_sales column alias was corrupted"
    assert "cume_sales AS store_sales" in q51, (
        "Q51: store_sales column alias was corrupted"
    )


# ---- sqlglot parsing ----


def test_all_queries_parseable_after_rewrite():
    """At least 95 of 99 rewritten queries parse with sqlglot."""
    queries = get_queries("delta_router_tpcds", "sf1")
    parsed = 0
    failures = []
    for qid, sql in queries:
        try:
            result = sqlglot.parse(sql)
            if result:
                parsed += 1
        except Exception as e:
            failures.append((qid, str(e)[:80]))
    # All 99 should parse (AST-based templatization preserves structure)
    assert parsed >= 95, f"Only {parsed}/99 parsed. Failures: {failures}"
    # Expect 99/99 with AST approach
    assert parsed == 99, f"{99 - parsed} queries failed to parse: {failures}"


# ---- get_queries convenience function ----


def test_get_queries_returns_correct_count():
    """get_queries returns 99 tuples with int IDs and non-empty SQL."""
    result = get_queries("cat", "sf1")
    assert len(result) == 99
    for qid, sql in result:
        assert isinstance(qid, int), f"Query ID {qid} is not int"
        assert isinstance(sql, str), f"Query {qid} SQL is not str"
        assert len(sql.strip()) > 0, f"Query {qid} SQL is empty"


def test_get_queries_ids_are_sequential():
    """get_queries returns queries with IDs 1 through 99."""
    result = get_queries("c", "s")
    ids = [qid for qid, _ in result]
    assert ids == list(range(1, 100))


# ---- validate_queries ----


def test_validate_queries_returns_99_results():
    """validate_queries returns a result for each of the 99 queries."""
    results = validate_queries("cat", "sf1")
    assert len(results) == 99
    assert all(isinstance(qid, int) for qid, _ in results)


def test_validate_queries_mostly_parseable():
    """At least 90 of 99 queries parse successfully (None error)."""
    results = validate_queries("cat", "sf1")
    ok = sum(1 for _, err in results if err is None)
    assert ok >= 90, f"Only {ok}/99 parsed successfully"
    # With AST-based templatization, expect 99/99
    assert ok == 99, f"{99 - ok} queries failed validation"


def test_validate_queries_error_format():
    """Failed validations return non-empty error strings."""
    results = validate_queries("cat", "sf1")
    for qid, err in results:
        if err is not None:
            assert isinstance(err, str)
            assert len(err) > 0
