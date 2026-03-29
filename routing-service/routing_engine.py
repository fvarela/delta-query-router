"""Routing decision pipeline — decides which engine executes a query."""

import fnmatch
import logging
import time
from dataclasses import dataclass, field

import db
from catalog_service import TableMetadata
from query_analyzer import QueryAnalysis

logger = logging.getLogger("routing-service.routing_engine")

# Rule cache TTL in seconds
RULES_CACHE_TTL = 60

# In-memory rule cache
_rules_cache: list[dict] | None = None
_rules_cache_time: float = 0.0


@dataclass
class RoutingSettings:
    """Scoring weights and bonuses from the routing_settings table."""

    fit_weight: float = 0.5
    cost_weight: float = 0.5
    running_bonus_duckdb: float = 0.05
    running_bonus_databricks: float = 0.15


@dataclass
class EngineStates:
    """Runtime state of engines at routing time."""

    duckdb_running: bool = False
    databricks_running: bool = False


@dataclass
class RoutingDecision:
    engine: str  # 'duckdb' or 'databricks'
    stage: (
        str  # 'SYSTEM_RULE', 'USER_RULE', 'ML_MODEL', 'FORCED', 'SCORING', 'FALLBACK'
    )
    reason: str
    complexity_score: float
    rule_id: int | None = None


@dataclass
class RoutingLogEvent:
    timestamp: str  # HH:MM:SS.mmm
    level: str  # "info, "rule", "decision", "warn", "error"
    stage: str
    message: str


@dataclass
class RoutingResult:
    decision: RoutingDecision
    events: list[RoutingLogEvent]


def _ts() -> str:
    """Return current time as HH:MM:SS.mmm for log events."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _load_rules(system: bool) -> list[dict]:
    """Load routing rules from DB, with 60-second in-memory cache."""
    global _rules_cache, _rules_cache_time
    now = time.monotonic()
    if _rules_cache is not None and (now - _rules_cache_time) < RULES_CACHE_TTL:
        return [r for r in _rules_cache if r["is_system"] == system]
    rows = db.fetch_all(
        "SELECT id, priority, condition_type, condition_value, target_engine, is_system "
        "FROM routing_rules WHERE enabled = true ORDER BY priority"
    )
    _rules_cache = rows
    _rules_cache_time = now
    return [r for r in _rules_cache if r["is_system"] == system]


def _match_rule(
    rule: dict, analysis: QueryAnalysis, table_metadata: dict[str, TableMetadata]
) -> bool:
    """Check if a routing rule matches the given query analysis and table metadata."""
    ctype = rule["condition_type"]
    cvalue = rule["condition_value"]
    tables = table_metadata.values()

    if ctype == "table_type":
        return any(t.table_type == cvalue for t in tables)

    if ctype == "has_governance":
        if cvalue == "row_filter":
            return any(t.has_rls for t in tables)
        if cvalue == "column_mask":
            return any(t.has_column_masking for t in tables)

    if ctype == "external_access":
        if cvalue == "false":
            return any(not t.external_engine_read_support for t in tables)

    if ctype == "complexity_gt":
        try:
            threshold = float(cvalue)
        except ValueError:
            return False
        return analysis.complexity_score > threshold

    if ctype == "table_name_pattern":
        return any(fnmatch.fnmatch(t.full_name, cvalue) for t in tables)

    return False


def _is_duckdb_compatible(table_metadata: dict[str, TableMetadata]) -> bool:
    """Check if all tables in the query can be read by DuckDB."""
    return all(
        (t.table_type in ("MANAGED", "EXTERNAL", "UNKNOWN"))
        and t.external_engine_read_support
        and t.data_source_format in ("DELTA", "PARQUET", "UNKNOWN")
        for t in table_metadata.values()
    )


def _score_engines(
    complexity: float,
    table_metadata: dict[str, TableMetadata],
    settings: RoutingSettings,
    engine_states: EngineStates,
    events: list[RoutingLogEvent],
) -> dict[str, float]:
    """Compute a weighted score for each candidate engine.

    Fit model (heuristic, no ML) — measures query-engine architectural fit,
    NOT actual execution speed:
      - DuckDB:      1.0 for complexity < 2, linear decay to 0.2 at complexity 10+
      - Databricks:  0.4 baseline (cold-start overhead), rises to 0.9 at complexity 10+

    Cost-efficiency model (higher = cheaper):
      - DuckDB:      0.7  (dedicated worker, no per-query cost)
      - Databricks:  0.2  (pay-per-query)

    Final score = fit_weight * fit + cost_weight * cost + running_bonus
    """
    duckdb_ok = _is_duckdb_compatible(table_metadata)

    # --- Fit scores (query-engine architectural fit) ---
    # DuckDB excels at simple queries on compatible tables
    if duckdb_ok:
        duckdb_fit = max(0.2, 1.0 - (complexity / 12.5))
    else:
        duckdb_fit = 0.0  # Can't run here at all

    # Databricks has cold-start overhead but handles complexity well
    databricks_fit = min(0.9, 0.4 + (complexity / 16.0))

    # --- Cost-efficiency scores (higher = cheaper) ---
    duckdb_cost = 0.7 if duckdb_ok else 0.0
    databricks_cost = 0.2

    # --- Weighted base scores ---
    fw = settings.fit_weight
    cw = settings.cost_weight
    duckdb_base = fw * duckdb_fit + cw * duckdb_cost
    databricks_base = fw * databricks_fit + cw * databricks_cost

    # --- Running bonuses (only for eligible, running engines) ---
    duckdb_bonus = (
        settings.running_bonus_duckdb
        if (engine_states.duckdb_running and duckdb_ok)
        else 0.0
    )
    databricks_bonus = (
        settings.running_bonus_databricks if engine_states.databricks_running else 0.0
    )

    duckdb_total = duckdb_base + duckdb_bonus
    databricks_total = databricks_base + databricks_bonus

    # --- Log the scoring breakdown ---
    events.append(
        RoutingLogEvent(
            _ts(), "info", "scoring", f"Weights: fit={fw:.0%} cost={cw:.0%}"
        )
    )
    events.append(
        RoutingLogEvent(_ts(), "info", "scoring", f"DuckDB compatible: {duckdb_ok}")
    )
    if duckdb_ok:
        events.append(
            RoutingLogEvent(
                _ts(),
                "info",
                "scoring",
                f"DuckDB:      fit={duckdb_fit:.2f} cost={duckdb_cost:.2f} "
                f"base={duckdb_base:.2f} bonus={duckdb_bonus:.2f} → total={duckdb_total:.2f}",
            )
        )
    else:
        events.append(
            RoutingLogEvent(
                _ts(),
                "info",
                "scoring",
                f"DuckDB:      ineligible (tables not compatible)",
            )
        )
    events.append(
        RoutingLogEvent(
            _ts(),
            "info",
            "scoring",
            f"Databricks:  fit={databricks_fit:.2f} cost={databricks_cost:.2f} "
            f"base={databricks_base:.2f} bonus={databricks_bonus:.2f} → total={databricks_total:.2f}",
        )
    )

    return {"duckdb": duckdb_total, "databricks": databricks_total}


def route_query(
    analysis: QueryAnalysis,
    table_metadata: dict[str, TableMetadata],
    routing_mode: str = "smart",
    settings: RoutingSettings | None = None,
    engine_states: EngineStates | None = None,
) -> RoutingResult:
    events: list[RoutingLogEvent] = []
    # 0. Error check
    if analysis.error is not None:
        raise ValueError(f"Cannot route query: {analysis.error}")
    score = analysis.complexity_score
    # Parse stage events
    events.append(RoutingLogEvent(_ts(), "info", "parse", "Received query for routing"))
    events.append(
        RoutingLogEvent(
            _ts(), "info", "parse", f"Statement type: {analysis.statement_type}"
        )
    )
    events.append(
        RoutingLogEvent(
            _ts(),
            "info",
            "parse",
            f"Tables referenced: {', '.join(analysis.tables) or 'none'}",
        )
    )
    events.append(RoutingLogEvent(_ts(), "info", "parse", f"Complexity score: {score}"))
    # 1. System hard rules
    events.append(RoutingLogEvent(_ts(), "info", "rules", "Evaluating system rules"))
    system_rules = _load_rules(system=True)
    for rule in system_rules:
        if _match_rule(rule, analysis, table_metadata):
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "rule",
                    "rules",
                    f"System rule matched: {rule['condition_type']}={rule['condition_value']} → {rule['target_engine']}",
                )
            )
            decision = RoutingDecision(
                engine=rule["target_engine"],
                stage="SYSTEM_RULE",
                reason=f"System rule: {rule['condition_type']}={rule['condition_value']}",
                complexity_score=score,
                rule_id=rule["id"],
            )
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "decision",
                    "engine",
                    f"Selected engine: {decision.engine} (stage={decision.stage})",
                )
            )
            return RoutingResult(decision=decision, events=events)
        else:
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "info",
                    "rules",
                    f"System rule skipped: {rule['condition_type']}={rule['condition_value']}",
                )
            )
    events.append(RoutingLogEvent(_ts(), "info", "rules", "No system rules matched"))
    # 2. Forced mode
    if routing_mode in ("duckdb", "databricks"):
        events.append(
            RoutingLogEvent(_ts(), "info", "rules", f"Forced mode: {routing_mode}")
        )
        decision = RoutingDecision(
            engine=routing_mode,
            stage="FORCED",
            reason=f"User selected {routing_mode}",
            complexity_score=score,
        )
        events.append(
            RoutingLogEvent(
                _ts(),
                "decision",
                "engine",
                f"Selected engine: {decision.engine} (stage={decision.stage})",
            )
        )
        return RoutingResult(decision=decision, events=events)
    # 3. User-defined rules
    events.append(RoutingLogEvent(_ts(), "info", "rules", "Evaluating user rules"))
    user_rules = _load_rules(system=False)
    for rule in user_rules:
        if _match_rule(rule, analysis, table_metadata):
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "rule",
                    "rules",
                    f"User rule #{rule['id']} matched: {rule['condition_type']}={rule['condition_value']} → {rule['target_engine']}",
                )
            )
            decision = RoutingDecision(
                engine=rule["target_engine"],
                stage="USER_RULE",
                reason=f"User rule #{rule['id']}: {rule['condition_type']}={rule['condition_value']}",
                complexity_score=score,
                rule_id=rule["id"],
            )
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "decision",
                    "engine",
                    f"Selected engine: {decision.engine} (stage={decision.stage})",
                )
            )
            return RoutingResult(decision=decision, events=events)
        else:
            events.append(
                RoutingLogEvent(
                    _ts(),
                    "info",
                    "rules",
                    f"User rule #{rule['id']} skipped: {rule['condition_type']}={rule['condition_value']}",
                )
            )
    events.append(RoutingLogEvent(_ts(), "info", "rules", "No user rules matched"))
    # 4. ML model stub
    events.append(
        RoutingLogEvent(
            _ts(), "info", "ml_model", "ML model evaluation (stub — no model loaded)"
        )
    )
    events.append(
        RoutingLogEvent(_ts(), "warn", "ml_model", "No ML model available, skipping")
    )
    ml_decision = None
    if ml_decision is not None:
        return RoutingResult(decision=ml_decision, events=events)
    # 5. Scoring
    _settings = settings or RoutingSettings()
    _engine_states = engine_states or EngineStates()
    events.append(
        RoutingLogEvent(_ts(), "info", "scoring", "Evaluating scoring heuristic")
    )
    scores = _score_engines(score, table_metadata, _settings, _engine_states, events)
    winner = max(scores, key=scores.get)  # type: ignore[arg-type]
    margin = abs(scores["duckdb"] - scores["databricks"])
    events.append(
        RoutingLogEvent(
            _ts(), "info", "scoring", f"Winner: {winner} (margin={margin:.2f})"
        )
    )
    decision = RoutingDecision(
        engine=winner,
        stage="SCORING",
        reason=f"Scoring: {winner} scored {scores[winner]:.2f} "
        f"(duckdb={scores['duckdb']:.2f}, databricks={scores['databricks']:.2f})",
        complexity_score=score,
    )
    events.append(
        RoutingLogEvent(
            _ts(),
            "decision",
            "engine",
            f"Selected engine: {decision.engine} (stage={decision.stage})",
        )
    )
    return RoutingResult(decision=decision, events=events)
