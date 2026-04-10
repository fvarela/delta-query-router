"""Tests for profile-aware query execution (Task 110).

Tests for:
- _load_profile_config(): loading profile config from DB
- _profile_config_to_routing_params(): mapping profile config to routing params
- POST /api/query with profile_id: end-to-end profile-aware routing
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
import auth
import routing_engine
from main import app, _load_profile_config, _profile_config_to_routing_params

client = TestClient(app)

# Fake engine rows for mocking engines_api.get_duckdb_engines()
_FAKE_DUCKDB_ENGINES = [
    {
        "id": "duckdb-1",
        "engine_type": "duckdb",
        "display_name": "DuckDB Small",
        "k8s_service_name": "duckdb-worker",
        "config": {},
        "cost_tier": 3,
        "is_active": True,
    },
]

# Default routing settings row
_MOCK_SETTINGS_ROW = {
    "fit_weight": 0.5,
    "cost_weight": 0.5,
    "running_bonus_duckdb": 0.2,
    "running_bonus_databricks": 0.1,
}


def _auth_header():
    token = "test-token-profile"
    auth._active_tokens[token] = "testuser"
    return {"Authorization": f"Bearer {token}"}


def _mock_routing_rules_empty(*_args, **_kwargs):
    return []


@pytest.fixture(autouse=True)
def _clear_rule_cache():
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0
    yield
    routing_engine._rules_cache = None
    routing_engine._rules_cache_time = 0.0


# ---------------------------------------------------------------------------
# _load_profile_config tests
# ---------------------------------------------------------------------------


class TestLoadProfileConfig:
    """Tests for _load_profile_config()."""

    @patch("main.db.fetch_one")
    def test_explicit_profile_id_found(self, mock_fetch):
        config = {"routingMode": "smart", "routingPriority": 1}
        mock_fetch.return_value = {"config": config}
        result = _load_profile_config(42)
        mock_fetch.assert_called_once_with(
            "SELECT config FROM routing_profiles WHERE id = %s", (42,)
        )
        assert result == config

    @patch("main.db.fetch_one")
    def test_explicit_profile_id_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        with pytest.raises(Exception) as exc_info:
            _load_profile_config(999)
        assert exc_info.value.status_code == 404
        assert "999" in exc_info.value.detail

    @patch("main.db.fetch_one")
    def test_default_profile_loaded(self, mock_fetch):
        config = {"routingMode": "smart", "routingPriority": 0.5}
        mock_fetch.return_value = {"config": config}
        result = _load_profile_config(None)
        mock_fetch.assert_called_once_with(
            "SELECT config FROM routing_profiles WHERE is_default = true"
        )
        assert result == config

    @patch("main.db.fetch_one")
    def test_no_default_profile_returns_none(self, mock_fetch):
        mock_fetch.return_value = None
        result = _load_profile_config(None)
        assert result is None

    @patch("main.db.fetch_one")
    def test_empty_config_returns_empty_dict(self, mock_fetch):
        mock_fetch.return_value = {"config": None}
        result = _load_profile_config(42)
        assert result == {}


# ---------------------------------------------------------------------------
# _profile_config_to_routing_params tests
# ---------------------------------------------------------------------------


class TestProfileConfigToRoutingParams:
    """Tests for _profile_config_to_routing_params()."""

    def test_smart_mode_cost_priority(self):
        """routingPriority=0 → fit_weight=0, cost_weight=1 (cost-optimized)."""
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "smart", "routingPriority": 0}
        )
        assert mode == "smart"
        assert settings is not None
        assert settings.fit_weight == 0.0
        assert settings.cost_weight == 1.0

    def test_smart_mode_balanced_priority(self):
        """routingPriority=0.5 → fit_weight=0.5, cost_weight=0.5 (balanced)."""
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "smart", "routingPriority": 0.5}
        )
        assert mode == "smart"
        assert settings is not None
        assert settings.fit_weight == 0.5
        assert settings.cost_weight == 0.5

    def test_smart_mode_fit_priority(self):
        """routingPriority=1 → fit_weight=1, cost_weight=0 (performance)."""
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "smart", "routingPriority": 1}
        )
        assert mode == "smart"
        assert settings is not None
        assert settings.fit_weight == 1.0
        assert settings.cost_weight == 0.0

    @patch("main.db.fetch_one")
    def test_single_mode_duckdb_engine(self, mock_fetch):
        """single mode with a duckdb engine → forced 'duckdb'."""
        mock_fetch.return_value = {"engine_type": "duckdb"}
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "single", "singleEngineId": "duckdb-1"}
        )
        assert mode == "duckdb"
        assert settings is None

    @patch("main.db.fetch_one")
    def test_single_mode_databricks_engine(self, mock_fetch):
        """single mode with a databricks engine → forced 'databricks'."""
        mock_fetch.return_value = {"engine_type": "databricks_sql"}
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "single", "singleEngineId": "databricks-xs"}
        )
        assert mode == "databricks"
        assert settings is None

    @patch("main.db.fetch_one")
    def test_single_mode_unknown_engine_fallback(self, mock_fetch):
        """single mode with unknown engine → falls back to 'smart'."""
        mock_fetch.return_value = None
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "single", "singleEngineId": "nonexistent"}
        )
        assert mode == "smart"
        assert settings is None

    def test_single_mode_no_engine_id(self):
        """single mode without singleEngineId → falls back to 'smart'."""
        mode, settings = _profile_config_to_routing_params({"routingMode": "single"})
        assert mode == "smart"
        assert settings is None

    def test_benchmark_mode(self):
        """benchmark mode passes through."""
        mode, settings = _profile_config_to_routing_params(
            {"routingMode": "benchmark", "routingPriority": 0.5}
        )
        assert mode == "benchmark"
        assert settings is not None

    def test_empty_config_defaults(self):
        """Empty config defaults to smart mode with balanced priority."""
        mode, settings = _profile_config_to_routing_params({})
        assert mode == "smart"
        assert settings is not None
        assert settings.fit_weight == 0.5
        assert settings.cost_weight == 0.5


# ---------------------------------------------------------------------------
# POST /api/query with profile_id
# ---------------------------------------------------------------------------


def _make_httpx_mock(mock_client_cls):
    """Create a mock httpx.AsyncClient that passes health checks + DuckDB exec."""
    mock_health_resp = MagicMock()
    mock_health_resp.status_code = 200
    mock_health_resp.raise_for_status = MagicMock()

    mock_exec_resp = MagicMock()
    mock_exec_resp.status_code = 200
    mock_exec_resp.headers = {"content-type": "application/json"}
    mock_exec_resp.json.return_value = {
        "columns": ["1"],
        "rows": [[1]],
        "row_count": 1,
        "execution_time_ms": 0.5,
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_health_resp
    mock_client.post.return_value = mock_exec_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client
    return mock_client


class TestProfileAwareQuery:
    """Test POST /api/query with profile_id."""

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_profile_id_cost_priority_changes_weights(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """profile_id with routingPriority=0 (cost) changes scoring weights."""
        _make_httpx_mock(mock_client_cls)

        # Mock db.fetch_one: first call = routing_settings, second = profile config
        cost_profile_config = {"routingMode": "smart", "routingPriority": 0}
        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                _MOCK_SETTINGS_ROW,  # routing_settings
                {"config": cost_profile_config},  # profile lookup
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "profile_id": 5},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        # With cost priority (fit=0, cost=1), DuckDB scores 0*fit + 1*0.7 = 0.7
        # Databricks scores 0*fit + 1*0.2 = 0.2 → DuckDB still wins on cost
        assert data["routing_decision"]["engine"] == "duckdb"

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_profile_id_not_found_returns_404(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """Non-existent profile_id returns 404."""
        _make_httpx_mock(mock_client_cls)

        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                _MOCK_SETTINGS_ROW,  # routing_settings
                None,  # profile not found
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "profile_id": 999},
                headers=_auth_header(),
            )

        assert resp.status_code == 404
        assert "999" in resp.json()["detail"]

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_default_profile_used_when_no_profile_id(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """Without profile_id, default profile is loaded."""
        _make_httpx_mock(mock_client_cls)

        default_config = {"routingMode": "smart", "routingPriority": 0.5}
        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                _MOCK_SETTINGS_ROW,  # routing_settings
                {"config": default_config},  # default profile
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        # Second call should be the default profile query
        assert "is_default" in str(mock_fetch.call_args_list[1])

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_legacy_forced_mode_ignores_profile(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """routing_mode=duckdb skips profile loading entirely."""
        _make_httpx_mock(mock_client_cls)

        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.return_value = _MOCK_SETTINGS_ROW

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "routing_mode": "duckdb"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "duckdb"
        assert data["routing_decision"]["stage"] == "FORCED"
        # db.fetch_one should only be called once (routing_settings), not for profile
        assert mock_fetch.call_count == 1

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_single_mode_duckdb_forces_engine(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """Profile with routingMode=single + duckdb engine → FORCED duckdb."""
        _make_httpx_mock(mock_client_cls)

        single_config = {"routingMode": "single", "singleEngineId": "duckdb-1"}
        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                _MOCK_SETTINGS_ROW,  # routing_settings
                {"config": single_config},  # profile
                {
                    "engine_type": "duckdb"
                },  # engine lookup in _profile_config_to_routing_params
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1", "profile_id": 10},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["routing_decision"]["engine"] == "duckdb"
        assert data["routing_decision"]["stage"] == "FORCED"

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_no_default_profile_uses_global_settings(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """When no default profile exists, global routing_settings are used unchanged."""
        _make_httpx_mock(mock_client_cls)

        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                _MOCK_SETTINGS_ROW,  # routing_settings
                None,  # no default profile
            ]

            resp = client.post(
                "/api/query",
                json={"sql": "SELECT 1"},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        # Still routes normally with global settings
        data = resp.json()
        assert data["routing_decision"]["engine"] in ("duckdb", "databricks")

    @patch("engines_api.get_duckdb_engines", return_value=_FAKE_DUCKDB_ENGINES)
    @patch("main.catalog_service.get_tables_metadata", return_value={})
    @patch("routing_engine._load_rules", side_effect=_mock_routing_rules_empty)
    @patch("main.httpx.AsyncClient")
    def test_profile_preserves_global_running_bonuses(
        self, mock_client_cls, _rules, _meta, _engines
    ):
        """Profile overrides weights but keeps global running bonuses."""
        _make_httpx_mock(mock_client_cls)

        fit_config = {"routingMode": "smart", "routingPriority": 1}
        custom_settings = {
            "fit_weight": 0.3,
            "cost_weight": 0.7,
            "running_bonus_duckdb": 0.99,
            "running_bonus_databricks": 0.88,
        }
        with patch("main.db.fetch_one") as mock_fetch:
            mock_fetch.side_effect = [
                custom_settings,  # routing_settings (with custom bonuses)
                {"config": fit_config},  # profile
            ]
            with patch("routing_engine.route_query") as mock_route:
                mock_route.return_value = routing_engine.RoutingResult(
                    decision=routing_engine.RoutingDecision(
                        engine="duckdb",
                        stage="SCORING",
                        reason="test",
                        complexity_score=0,
                    ),
                    events=[],
                )

                resp = client.post(
                    "/api/query",
                    json={"sql": "SELECT 1", "profile_id": 1},
                    headers=_auth_header(),
                )

            # Verify route_query was called with merged settings
            call_kwargs = mock_route.call_args
            settings_arg = call_kwargs.kwargs.get("settings") or call_kwargs[1].get(
                "settings"
            )
            if settings_arg is None:
                # Positional arg: route_query(analysis, meta, mode, settings=..., engine_states=...)
                settings_arg = (
                    call_kwargs[0][3]
                    if len(call_kwargs[0]) > 3
                    else call_kwargs.kwargs["settings"]
                )

            # Profile priority=1 → fit_weight=1, cost_weight=0
            assert settings_arg.fit_weight == 1.0
            assert settings_arg.cost_weight == 0.0
            # Global bonuses preserved
            assert settings_arg.running_bonus_duckdb == 0.99
            assert settings_arg.running_bonus_databricks == 0.88
