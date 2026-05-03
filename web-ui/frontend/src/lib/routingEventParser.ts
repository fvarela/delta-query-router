/**
 * routingEventParser.ts — Parses routing_log_events (text-based) into
 * structured RoutingDecisionData for RoutingDecisionView.
 */

import type { RoutingLogEvent } from "@/types";
import type { EngineCatalogEntry, RoutingSettings, WarehouseMapping } from "@/types";

// ── Types (exported for RoutingDecisionView) ─────────────────────────────────

export interface ParsedQuery {
  sql: string;
  statementType: string;
  tables: string[];
  complexityScore: number;
}

export interface RuleEvaluation {
  name: string;
  description: string;
  matched: boolean;
  detail?: string;
}

export interface EngineScore {
  engineId: string;
  displayName: string;
  engineType: "duckdb" | "databricks";
  predictedMs: number;
  coldStartMs: number;
  totalMs: number;
  costTier: number;
  normLatency: number;
  normCost: number;
  latencyContribution: number;
  costContribution: number;
  weightedScore: number;
  isEligible: boolean;
  filterReason?: string;
  isWinner: boolean;
  runtimeState: "running" | "stopped" | "starting" | "unknown";
}

export interface RoutingDecisionData {
  query: ParsedQuery;
  rules: RuleEvaluation[];
  engines: EngineScore[];
  weights: { fit: number; cost: number };
  winnerEngineId: string;
  winnerDisplayName: string;
  stage: string;
  executionTimeMs: number;
}

// ── Rule metadata map ────────────────────────────────────────────────────────

const RULE_META: Record<string, { name: string; description: string }> = {
  "table_type=VIEW": {
    name: "View tables",
    description: "Routes views to Databricks (views cannot be read externally)",
  },
  "has_rls=true": {
    name: "Row-level security",
    description: "Routes tables with row filters to Databricks (security boundary)",
  },
  "has_column_masking=true": {
    name: "Column masking",
    description: "Routes tables with column masks to Databricks (security boundary)",
  },
  "table_type=FOREIGN": {
    name: "Foreign tables",
    description: "Routes foreign/federated tables to Databricks",
  },
  "external_engine_read_support=false": {
    name: "External access",
    description: "Routes tables without external engine read support to Databricks",
  },
};

// ── Parser ───────────────────────────────────────────────────────────────────

interface ParseContext {
  engines: EngineCatalogEntry[];
  routingSettings: RoutingSettings;
  enabledEngineIds: Set<string>;
  warehouseMappings: WarehouseMapping[];
}

/**
 * Parse routing_log_events + routing_decision into RoutingDecisionData.
 */
export function parseRoutingEvents(
  events: RoutingLogEvent[],
  routingDecision: {
    engine: string;
    engine_display_name: string;
    stage?: string;
    reason: string;
    complexity_score: number;
    compute_time_ms?: number;
    cold_start_ms?: number;
    total_latency_ms?: number;
  },
  sql: string,
  executionTimeMs: number,
  ctx: ParseContext,
): RoutingDecisionData {
  let statementType = "SELECT";
  let tables: string[] = [];
  let complexityScore = routingDecision.complexity_score;

  // Per-engine parsed data (ML scoring)
  const predictionMap = new Map<string, { predicted: number; coldStart: number; total: number; costTier: number }>();
  const normMap = new Map<string, { normLat: number; normCost: number; score: number }>();
  const eligibleSet = new Set<string>();
  let winnerId = "";

  // Weights from the routing events (historical, not live)
  let eventFitWeight: number | null = null;
  let eventCostWeight: number | null = null;

  // Heuristic scoring data
  const heuristicMap = new Map<string, { fit: number; cost: number; total: number }>();

  // Rules
  const matchedRules = new Set<string>();
  const skippedRules = new Set<string>();

  for (const ev of events) {
    const msg = ev.message;

    // Statement type
    const stMatch = msg.match(/^Statement type: (.+)$/);
    if (stMatch) { statementType = stMatch[1]; continue; }

    // Tables referenced
    const tabMatch = msg.match(/^Tables referenced: (.+)$/);
    if (tabMatch && tabMatch[1] !== "none") {
      tables = tabMatch[1].split(",").map(t => t.trim());
      continue;
    }

    // Complexity score
    const cxMatch = msg.match(/^Complexity score: ([\d.]+)$/);
    if (cxMatch) { complexityScore = parseFloat(cxMatch[1]); continue; }

    // ML scoring weights: "Weights: performance=0% cost=100%"
    const wMatch = msg.match(/^Weights: performance=(\d+)% cost=(\d+)%$/);
    if (wMatch) {
      eventFitWeight = parseInt(wMatch[1]) / 100;
      eventCostWeight = parseInt(wMatch[2]) / 100;
      continue;
    }

    // Heuristic scoring weights: "Weights: fit=0% cost=100%"
    const hwMatch = msg.match(/^Weights: fit=(\d+)% cost=(\d+)%$/);
    if (hwMatch) {
      eventFitWeight = parseInt(hwMatch[1]) / 100;
      eventCostWeight = parseInt(hwMatch[2]) / 100;
      continue;
    }

    // System rule matched
    const rmMatch = msg.match(/^System rule matched: (.+?) → (.+)$/);
    if (rmMatch) { matchedRules.add(rmMatch[1]); continue; }

    // System rule skipped
    const rsMatch = msg.match(/^System rule skipped: (.+)$/);
    if (rsMatch) { skippedRules.add(rsMatch[1]); continue; }

    // Engine prediction: "duckdb-1: predicted=122717ms cold_start=0ms → total=122717ms (cost_tier=3)"
    const predMatch = msg.match(/^(.+?): predicted=(\d+)ms cold_start=(\d+)ms → total=(\d+)ms \(cost_tier=(.+?)\)$/);
    if (predMatch) {
      predictionMap.set(predMatch[1], {
        predicted: parseInt(predMatch[2]),
        coldStart: parseInt(predMatch[3]),
        total: parseInt(predMatch[4]),
        costTier: parseFloat(predMatch[5]),
      });
      continue;
    }

    // Norm scores: "duckdb-1: norm_lat=1.000 norm_cost=0.000 → score=0.500"
    const normMatch = msg.match(/^(.+?): norm_lat=([\d.]+) norm_cost=([\d.]+) → score=([\d.]+)$/);
    if (normMatch) {
      normMap.set(normMatch[1], {
        normLat: parseFloat(normMatch[2]),
        normCost: parseFloat(normMatch[3]),
        score: parseFloat(normMatch[4]),
      });
      continue;
    }

    // Eligible engines: "Eligible engines (user selection): duckdb-1, databricks-xs"
    const eligMatch = msg.match(/^Eligible engines \(user selection\): (.+)$/);
    if (eligMatch && eligMatch[1] !== "none") {
      eligMatch[1].split(",").map(s => s.trim()).forEach(id => eligibleSet.add(id));
      continue;
    }

    // Heuristic scoring: "DuckDB:      fit=1.00 cost=0.70 → total=0.85"
    const heurMatch = msg.match(/^(\w+):\s+fit=([\d.]+)\s+cost=([\d.]+)\s+→\s+total=([\d.]+)$/);
    if (heurMatch) {
      const rawName = heurMatch[1]; // "DuckDB" or "Databricks"
      heuristicMap.set(rawName, {
        fit: parseFloat(heurMatch[2]),
        cost: parseFloat(heurMatch[3]),
        total: parseFloat(heurMatch[4]),
      });
      continue;
    }

    // Winner: "Winner: duckdb-1 (score=0.500)" or "Winner: duckdb (margin=0.00)"
    const winMatch = msg.match(/^Winner: (.+?) \((?:score|margin)=/);
    if (winMatch) { winnerId = winMatch[1]; continue; }
  }

  // Build rules array from all known rules
  const allRuleKeys = new Set([...matchedRules, ...skippedRules]);
  const rules: RuleEvaluation[] = [];
  for (const key of allRuleKeys) {
    const meta = RULE_META[key] || { name: key, description: "" };
    rules.push({
      name: meta.name,
      description: meta.description,
      matched: matchedRules.has(key),
      detail: matchedRules.has(key) ? undefined : `Rule did not match`,
    });
  }
  // Sort: matched first, then by name
  rules.sort((a, b) => (a.matched === b.matched ? a.name.localeCompare(b.name) : a.matched ? -1 : 1));

  // Build engines array — use historical weights from events if available, fall back to live context
  const fw = eventFitWeight ?? ctx.routingSettings.fit_weight;
  const cw = eventCostWeight ?? ctx.routingSettings.cost_weight;

  // If no prediction data from events, fall back to the decision winner only
  if (!winnerId && routingDecision.engine) {
    winnerId = routingDecision.engine;
  }

  const engineScores: EngineScore[] = [];

  // Heuristic fallback: if we have heuristic data but no ML prediction data, build engines from it
  if (heuristicMap.size > 0 && predictionMap.size === 0) {
    const nameToType: Record<string, "duckdb" | "databricks"> = {
      DuckDB: "duckdb",
      Databricks: "databricks",
    };

    for (const [rawName, h] of heuristicMap) {
      const engineType = nameToType[rawName] ?? (rawName.toLowerCase().startsWith("duckdb") ? "duckdb" : "databricks");
      const eid = rawName.toLowerCase(); // "duckdb" or "databricks"

      engineScores.push({
        engineId: eid,
        displayName: rawName,
        engineType,
        predictedMs: 0,
        coldStartMs: 0,
        totalMs: 0,
        costTier: 0,
        normLatency: h.fit,
        normCost: h.cost,
        latencyContribution: fw * h.fit,
        costContribution: cw * h.cost,
        weightedScore: h.total,
        isEligible: true,
        isWinner: eid === winnerId,
        runtimeState: "unknown",
      });
    }
  } else {
  // ML scoring path: build from predictionMap + catalog
  const allEngineIds = new Set([...predictionMap.keys(), ...ctx.engines.map(e => e.id)]);

  for (const eid of allEngineIds) {
    const pred = predictionMap.get(eid);
    const norm = normMap.get(eid);
    const catalogEntry = ctx.engines.find(e => e.id === eid);

    // Skip engines that have no prediction data AND aren't in the catalog
    if (!pred && !catalogEntry) continue;
    // Skip engines that have no prediction data and no norm data (not scored)
    if (!pred && !norm) continue;

    const engineType: "duckdb" | "databricks" = (catalogEntry?.engine_type ?? eid).startsWith("duckdb") ? "duckdb" : "databricks";
    const displayName = catalogEntry?.display_name ?? eid;
    // Infer state at routing time from cold_start (historical, not live)
    const runtimeState: EngineScore["runtimeState"] = pred
      ? (pred.coldStart === 0 ? "running" : "stopped")
      : "unknown";

    const predictedMs = pred?.predicted ?? 0;
    const coldStartMs = pred?.coldStart ?? 0;
    const totalMs = pred?.total ?? 0;
    const costTier = pred?.costTier ?? 0;

    const normLatency = norm?.normLat ?? 0;
    const normCost = norm?.normCost ?? 0;
    const weightedScore = norm?.score ?? 0;

    const latencyContribution = fw * normLatency;
    const costContribution = cw * normCost;

    // Eligibility: if eligibleSet was populated, use it; otherwise check enabledEngineIds
    const hasEligibilityInfo = eligibleSet.size > 0;
    let isEligible = hasEligibilityInfo ? eligibleSet.has(eid) : ctx.enabledEngineIds.has(eid);
    let filterReason: string | undefined;

    if (!isEligible) {
      if (!ctx.enabledEngineIds.has(eid)) {
        filterReason = "Not selected";
      } else if (engineType === "databricks") {
        const mapping = ctx.warehouseMappings.find(m => m.engineId === eid);
        if (!mapping?.warehouseId) {
          filterReason = "No warehouse mapped";
        }
      }
      if (!filterReason) filterReason = "Not eligible";
    }

    // Check if engine was filtered in ML scoring events (e.g., no cold start data)
    if (isEligible && !norm && pred) {
      // Engine has prediction but no normalization data — it was filtered during scoring
      isEligible = false;
      filterReason = "No cold start data";
    }

    engineScores.push({
      engineId: eid,
      displayName,
      engineType,
      predictedMs,
      coldStartMs,
      totalMs,
      costTier,
      normLatency,
      normCost,
      latencyContribution,
      costContribution,
      weightedScore,
      isEligible,
      filterReason,
      isWinner: eid === winnerId,
      runtimeState,
    });
  }
  } // end ML scoring else

  // Sort: winner first, then eligible, then by score ascending
  engineScores.sort((a, b) => {
    if (a.isWinner !== b.isWinner) return a.isWinner ? -1 : 1;
    if (a.isEligible !== b.isEligible) return a.isEligible ? -1 : 1;
    return a.weightedScore - b.weightedScore;
  });

  const winnerEngine = engineScores.find(e => e.isWinner);
  const stage = routingDecision.stage ?? "ML_MODEL";

  return {
    query: { sql, statementType, tables, complexityScore },
    rules,
    engines: engineScores,
    weights: { fit: fw, cost: cw },
    winnerEngineId: winnerId,
    winnerDisplayName: winnerEngine?.displayName ?? routingDecision.engine_display_name ?? winnerId,
    stage,
    executionTimeMs,
  };
}
