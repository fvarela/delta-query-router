"""Tests for feature_builder module."""

from feature_builder import (
    FEATURE_NAMES,
    build_feature_vector,
    feature_dict_to_array,
    get_feature_names,
)
from query_analyzer import QueryAnalysis
from catalog_service import TableMetadata


def _make_analysis(**overrides) -> QueryAnalysis:
    """Create a QueryAnalysis with sensible defaults, overrideable."""
    defaults = dict(
        statement_type="SELECT",
        tables=["catalog.schema.t1", "catalog.schema.t2"],
        num_tables=2,
        num_joins=1,
        num_aggregations=1,
        num_subqueries=0,
        has_group_by=True,
        has_order_by=False,
        has_limit=True,
        has_window_functions=False,
        num_columns_selected=5,
        complexity_score=8.5,
        error=None,
    )
    defaults.update(overrides)
    return QueryAnalysis(**defaults)


def _make_metadata(full_name: str, size_bytes: int | None = 1000) -> TableMetadata:
    """Create a TableMetadata with defaults."""
    return TableMetadata(
        full_name=full_name,
        table_type="MANAGED",
        data_source_format="DELTA",
        storage_location="abfss://container@account.dfs.core.windows.net/path",
        size_bytes=size_bytes,
        has_rls=False,
        has_column_masking=False,
        external_engine_read_support=True,
        cached=True,
    )


class TestBuildFeatureVector:
    """Test build_feature_vector with various inputs."""

    def test_full_features(self):
        analysis = _make_analysis()
        metadata = {
            "catalog.schema.t1": _make_metadata("catalog.schema.t1", size_bytes=5000),
            "catalog.schema.t2": _make_metadata("catalog.schema.t2", size_bytes=3000),
        }
        features = build_feature_vector(analysis, metadata, "duckdb", 3)

        assert features["num_tables"] == 2.0
        assert features["num_joins"] == 1.0
        assert features["num_aggregations"] == 1.0
        assert features["num_subqueries"] == 0.0
        assert features["has_group_by"] == 1.0
        assert features["has_order_by"] == 0.0
        assert features["has_limit"] == 1.0
        assert features["has_window_functions"] == 0.0
        assert features["num_columns_selected"] == 5.0
        assert features["complexity_score"] == 8.5
        assert features["max_table_size_bytes"] == 5000.0
        assert features["total_data_bytes"] == 8000.0
        assert features["engine_type"] == 0.0  # duckdb
        assert features["cost_tier"] == 3.0

    def test_databricks_engine_type(self):
        analysis = _make_analysis()
        features = build_feature_vector(analysis, {}, "databricks", 7)
        assert features["engine_type"] == 1.0

    def test_unknown_engine_type_defaults_to_zero(self):
        analysis = _make_analysis()
        features = build_feature_vector(analysis, {}, "some_new_engine", 5)
        assert features["engine_type"] == 0.0

    def test_empty_table_metadata(self):
        analysis = _make_analysis(num_tables=0, tables=[])
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        assert features["max_table_size_bytes"] == 0.0
        assert features["total_data_bytes"] == 0.0

    def test_none_size_bytes_treated_as_zero(self):
        metadata = {
            "t1": _make_metadata("t1", size_bytes=None),
            "t2": _make_metadata("t2", size_bytes=2000),
        }
        analysis = _make_analysis()
        features = build_feature_vector(analysis, metadata, "duckdb", 3)
        assert features["max_table_size_bytes"] == 2000.0
        assert features["total_data_bytes"] == 2000.0

    def test_all_none_size_bytes(self):
        metadata = {
            "t1": _make_metadata("t1", size_bytes=None),
            "t2": _make_metadata("t2", size_bytes=None),
        }
        analysis = _make_analysis()
        features = build_feature_vector(analysis, metadata, "duckdb", 3)
        assert features["max_table_size_bytes"] == 0.0
        assert features["total_data_bytes"] == 0.0

    def test_boolean_features_false(self):
        analysis = _make_analysis(
            has_group_by=False,
            has_order_by=False,
            has_limit=False,
            has_window_functions=False,
        )
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        assert features["has_group_by"] == 0.0
        assert features["has_order_by"] == 0.0
        assert features["has_limit"] == 0.0
        assert features["has_window_functions"] == 0.0

    def test_boolean_features_true(self):
        analysis = _make_analysis(
            has_group_by=True,
            has_order_by=True,
            has_limit=True,
            has_window_functions=True,
        )
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        assert features["has_group_by"] == 1.0
        assert features["has_order_by"] == 1.0
        assert features["has_limit"] == 1.0
        assert features["has_window_functions"] == 1.0

    def test_feature_vector_has_all_keys(self):
        analysis = _make_analysis()
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        assert set(features.keys()) == set(FEATURE_NAMES)

    def test_feature_vector_length_consistent(self):
        analysis = _make_analysis()
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        assert len(features) == len(FEATURE_NAMES)

    def test_single_large_table(self):
        metadata = {
            "t1": _make_metadata("t1", size_bytes=10_000_000_000),
        }
        analysis = _make_analysis(num_tables=1, tables=["t1"])
        features = build_feature_vector(analysis, metadata, "duckdb", 3)
        assert features["max_table_size_bytes"] == 10_000_000_000.0
        assert features["total_data_bytes"] == 10_000_000_000.0


class TestFeatureDictToArray:
    """Test conversion from dict to ordered array."""

    def test_ordering_matches_feature_names(self):
        analysis = _make_analysis()
        features = build_feature_vector(analysis, {}, "duckdb", 3)
        array = feature_dict_to_array(features)
        assert len(array) == len(FEATURE_NAMES)
        # Verify ordering by checking a known position
        assert array[FEATURE_NAMES.index("engine_type")] == 0.0
        assert array[FEATURE_NAMES.index("cost_tier")] == 3.0

    def test_roundtrip_consistency(self):
        """Array values match dict values in FEATURE_NAMES order."""
        analysis = _make_analysis(num_joins=7, complexity_score=42.0)
        features = build_feature_vector(analysis, {}, "databricks", 9)
        array = feature_dict_to_array(features)
        for i, name in enumerate(FEATURE_NAMES):
            assert array[i] == features[name], f"Mismatch at {name}"


class TestGetFeatureNames:
    """Test get_feature_names utility."""

    def test_returns_list(self):
        names = get_feature_names()
        assert isinstance(names, list)
        assert len(names) == 14  # 10 query + 2 table + 2 engine

    def test_returns_copy(self):
        """Modifying return value doesn't affect module constant."""
        names = get_feature_names()
        names.append("bogus")
        assert "bogus" not in FEATURE_NAMES
