from query_analyzer import analyze_query

class TestEdgeCases:
    """Empty input, whitespace, and parse failures."""

    def test_empty_string(self):
        result = analyze_query("")
        assert result.error == "empty SQL"
        assert result.statement_type == "OTHER"
        assert result.complexity_score == 0
    
    def test_whitespace_only(self):
        result = analyze_query("   \n\t  ")
        assert result.error == "empty SQL"
    
    def test_invalid_sql(self):
        result = analyze_query("NOT VALID SQL ! @#$%")
        assert result is not None
    
    def test_multiple_statements_uses_first(self):
        result = analyze_query("SELECT 1; SELECT 2")
        assert result.statement_type == "SELECT"
        assert result.error is None

class TestStatementType:
    """Verify statement_type classification."""

    def test_select(self):
        result = analyze_query("SELECT 1")
        assert result.statement_type == "SELECT"
        assert result.error is None
    
    def test_create_table(self):
        result = analyze_query("CREATE TABLE foo (id INT)")
        assert result.statement_type == "CREATE"
    
    def test_insert(self):
        result = analyze_query("INSERT INTO foo VALUES (1)")
        assert result.statement_type == "INSERT"
    
    def test_drop_table(self):
        result = analyze_query("DROP TABLE foo")
        assert result.statement_type == "OTHER"

class TestFeatureExtraction:
    """Verify AST walking extracts correct features."""
    COMPLEX_QUERY = """
        SELECT c.name, SUM(s.amount)
        FROM catalog.schema.customers c
        JOIN catalog.schema.sales s ON c.id = s.customer_id
        GROUP BY c.name
        ORDER BY 2 DESC
        LIMIT 10
    """
    def test_tables_extracted(self):
        result = analyze_query(self.COMPLEX_QUERY)
        assert result.num_tables == 2
        assert "catalog.schema.customers" in result.tables
        assert "catalog.schema.sales" in result.tables
    def test_join_counted(self):
        result = analyze_query(self.COMPLEX_QUERY)
        assert result.num_joins == 1
    def test_aggregation_counted(self):
        result = analyze_query(self.COMPLEX_QUERY)
        assert result.num_aggregations == 1
    def test_clauses_detected(self):
        result = analyze_query(self.COMPLEX_QUERY)
        assert result.has_group_by is True
        assert result.has_order_by is True
        assert result.has_limit is True
        assert result.has_window_functions is False
    def test_columns_selected(self):
        result = analyze_query(self.COMPLEX_QUERY)
        assert result.num_columns_selected == 2

    def test_simple_select_minimal_features(self):
        result = analyze_query("SELECT 1")
        assert result.num_tables == 0
        assert result.num_joins == 0
        assert result.complexity_score == 0.0
    def test_window_function_detected(self):
        sql = "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM foo"
        result = analyze_query(sql)
        assert result.has_window_functions is True
    def test_subquery_counted(self):
        sql = "SELECT * FROM foo WHERE id IN (SELECT id FROM bar)"
        result = analyze_query(sql)
        assert result.num_subqueries >= 1

class TestComplexityScore:
    """Verify the weighted complexity formula."""
    def test_complex_query_score(self):
        sql = """
            SELECT c.name, SUM(s.amount)
            FROM catalog.schema.customers c
            JOIN catalog.schema.sales s ON c.id = s.customer_id
            GROUP BY c.name
            ORDER BY 2 DESC
            LIMIT 10
        """
        result = analyze_query(sql)
        # 1 join * 3 + 1 agg * 2 + 0 subq * 5 + group_by * 1
        # + order_by * 0.5 + 0 window * 4 + (2-1) tables * 1
        expected = 3 + 2 + 0 + 1 + 0.5 + 0 + 1
        assert result.complexity_score == expected
    def test_simple_select_zero_score(self):
        result = analyze_query("SELECT 1")
        assert result.complexity_score == 0.0