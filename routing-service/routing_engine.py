"""Routing decision pipeline — decides which engine executes a query."""

import fnmatch
import logging
import time
from dataclasses import dataclass

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
class RoutingDecision:
    engine: str  # 'duckdb' or 'databricks'
    stage: str  # 'SYSTEM_RULE', 'USER_RULE', 'ML_MODEL', 'FORCED', 'FALLBACK'
    reason: str
    complexity_score: float
    rule_id: int | None = None

@dataclass
class RoutingLogEvent:
    timestamp: str # HH:MM:SS.mmm
    level: str # "info, "rule", "decision", "warn", "error"
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


def route_query(
    analysis: QueryAnalysis,
    table_metadata: dict[str, TableMetadata],
    routing_mode: str = "smart",
) -> RoutingResult:
    events: list[RoutingLogEvent] = []
    # 0. Error check
    if analysis.error is not None:
        raise ValueError(f"Cannot route query: {analysis.error}")
    score = analysis.complexity_score
    # Parse stage events
    events.append(RoutingLogEvent(_ts(), "info", "parse", "Received query for routing"))
    events.append(RoutingLogEvent(_ts(), "info", "parse", f"Statement type: {analysis.statement_type}"))
    events.append(RoutingLogEvent(_ts(), "info", "parse", f"Tables referenced: {', '.join(analysis.tables) or 'none'}"))
    events.append(RoutingLogEvent(_ts(), "info", "parse", f"Complexity score: {score}"))
    # 1. System hard rules
    events.append(RoutingLogEvent(_ts(), "info", "rules", "Evaluating system rules"))
    system_rules = _load_rules(system=True)
    for rule in system_rules:
        if _match_rule(rule, analysis, table_metadata):
            events.append(RoutingLogEvent(_ts(), "rule", "rules",
                f"System rule matched: {rule['condition_type']}={rule['condition_value']} → {rule['target_engine']}"))
            decision = RoutingDecision(
                engine=rule["target_engine"], stage="SYSTEM_RULE",
                reason=f"System rule: {rule['condition_type']}={rule['condition_value']}",
                complexity_score=score, rule_id=rule["id"],
            )
            events.append(RoutingLogEvent(_ts(), "decision", "engine", f"Selected engine: {decision.engine} (stage={decision.stage})"))
            return RoutingResult(decision=decision, events=events)
        else:
            events.append(RoutingLogEvent(_ts(), "info", "rules",
                f"System rule skipped: {rule['condition_type']}={rule['condition_value']}"))
    events.append(RoutingLogEvent(_ts(), "info", "rules", "No system rules matched"))
    # 2. Forced mode
    if routing_mode in ("duckdb", "databricks"):
        events.append(RoutingLogEvent(_ts(), "info", "rules", f"Forced mode: {routing_mode}"))
        decision = RoutingDecision(
            engine=routing_mode, stage="FORCED",
            reason=f"User selected {routing_mode}", complexity_score=score,
        )
        events.append(RoutingLogEvent(_ts(), "decision", "engine", f"Selected engine: {decision.engine} (stage={decision.stage})"))
        return RoutingResult(decision=decision, events=events)
    # 3. User-defined rules
    events.append(RoutingLogEvent(_ts(), "info", "rules", "Evaluating user rules"))
    user_rules = _load_rules(system=False)
    for rule in user_rules:
        if _match_rule(rule, analysis, table_metadata):
            events.append(RoutingLogEvent(_ts(), "rule", "rules",
                f"User rule #{rule['id']} matched: {rule['condition_type']}={rule['condition_value']} → {rule['target_engine']}"))
            decision = RoutingDecision(
                engine=rule["target_engine"], stage="USER_RULE",
                reason=f"User rule #{rule['id']}: {rule['condition_type']}={rule['condition_value']}",
                complexity_score=score, rule_id=rule["id"],
            )
            events.append(RoutingLogEvent(_ts(), "decision", "engine", f"Selected engine: {decision.engine} (stage={decision.stage})"))
            return RoutingResult(decision=decision, events=events)
        else:
            events.append(RoutingLogEvent(_ts(), "info", "rules",
                f"User rule #{rule['id']} skipped: {rule['condition_type']}={rule['condition_value']}"))
    events.append(RoutingLogEvent(_ts(), "info", "rules", "No user rules matched"))
    # 4. ML model stub
    events.append(RoutingLogEvent(_ts(), "info", "ml_model", "ML model evaluation (stub — no model loaded)"))
    events.append(RoutingLogEvent(_ts(), "warn", "ml_model", "No ML model available, skipping"))
    ml_decision = None
    if ml_decision is not None:
        return RoutingResult(decision=ml_decision, events=events)
    # 5. Fallback heuristic
    events.append(RoutingLogEvent(_ts(), "info", "engine", "Applying fallback heuristic"))
    if score < 5 and all(
        (t.table_type in ("MANAGED", "EXTERNAL", "UNKNOWN"))
        and t.external_engine_read_support
        and t.data_source_format in ("DELTA", "PARQUET", "UNKNOWN")
        for t in table_metadata.values()
    ):
        decision = RoutingDecision(
            engine="duckdb", stage="FALLBACK",
            reason="Low complexity, all tables DuckDB-compatible", complexity_score=score,
        )
    else:
        decision = RoutingDecision(
            engine="databricks", stage="FALLBACK",
            reason="Default to Databricks", complexity_score=score,
        )
    events.append(RoutingLogEvent(_ts(), "decision", "engine", f"Selected engine: {decision.engine} (stage={decision.stage})"))
    return RoutingResult(decision=decision, events=events)