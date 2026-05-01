/**
 * RoutingDecisionView — structured routing decision breakdown.
 *
 * Replaces the raw routing log with a user-friendly view that explains
 * WHY the router picked a specific engine.
 *
 * Accepts parsed RoutingDecisionData as a prop (from routingEventParser).
 */

import React, { useState } from "react";
import {
  Database,
  Shield,
  Brain,
  Trophy,
  ChevronDown,
  ChevronRight,
  Check,
  X as XIcon,
  Minus,
  Zap,
  Clock,
  DollarSign,
  Filter,
} from "lucide-react";
import type { RoutingDecisionData } from "@/lib/routingEventParser";

// ── Utility components ───────────────────────────────────────────────────────

const SectionHeader: React.FC<{
  icon: React.ReactNode;
  title: string;
  badge?: React.ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
}> = ({ icon, title, badge, collapsed, onToggle }) => (
  <button
    onClick={onToggle}
    className="flex items-center gap-2 w-full text-left group"
  >
    {onToggle && (
      <span className="text-muted-foreground/60 group-hover:text-muted-foreground transition-colors">
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
      </span>
    )}
    <span className="text-primary/80">{icon}</span>
    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
      {title}
    </span>
    {badge}
  </button>
);

const StatePill: React.FC<{ state: string }> = ({ state }) => {
  const styles: Record<string, string> = {
    running: "bg-status-success/15 text-status-success",
    stopped: "bg-muted text-muted-foreground",
    starting: "bg-status-warning/15 text-status-warning",
    unknown: "bg-muted text-muted-foreground",
  };
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${styles[state] || styles.unknown}`}>
      {state}
    </span>
  );
};

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}

// ── Main component ───────────────────────────────────────────────────────────

export const RoutingDecisionView: React.FC<{
  data: RoutingDecisionData;
  onClose?: () => void;
}> = ({ data, onClose }) => {
  const [rulesExpanded, setRulesExpanded] = useState(false);
  const eligibleEngines = data.engines.filter((e) => e.isEligible);
  const filteredEngines = data.engines.filter((e) => !e.isEligible);
  const winner = data.engines.find((e) => e.isWinner);

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ── */}
      <div className="px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-[13px] font-semibold text-foreground">
              Routing Decision
            </h3>
            {winner && (
              <span className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                <Trophy size={10} />
                {winner.displayName}
              </span>
            )}
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
            >
              <XIcon size={16} />
            </button>
          )}
        </div>
        <p className="text-[11px] text-muted-foreground font-mono mt-1 truncate max-w-[600px]">
          {data.query.sql}
        </p>
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {/* ▸ Step 1: Query Analysis */}
        <div className="px-4 py-3 border-b border-border/60">
          <SectionHeader
            icon={<Database size={12} />}
            title="Query Analysis"
          />
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[11px]">
            <div>
              <span className="text-muted-foreground">Type </span>
              <span className="text-foreground font-medium">
                {data.query.statementType}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Tables </span>
              {data.query.tables.map((t) => (
                <span
                  key={t}
                  className="text-foreground font-mono bg-muted/50 px-1 py-0.5 rounded text-[10px]"
                >
                  {t}
                </span>
              ))}
            </div>
            <div>
              <span className="text-muted-foreground">Complexity </span>
              <span className="text-foreground font-medium">
                {data.query.complexityScore}
              </span>
            </div>
          </div>
        </div>

        {/* ▸ Step 2: System Rules */}
        <div className="px-4 py-3 border-b border-border/60">
          <SectionHeader
            icon={<Shield size={12} />}
            title="System Rules"
            badge={
              <span className="text-[10px] text-muted-foreground/70 ml-1">
                {data.rules.filter((r) => r.matched).length > 0
                  ? `${data.rules.filter((r) => r.matched).length} matched`
                  : "none matched — proceeding to ML"}
              </span>
            }
            collapsed={!rulesExpanded}
            onToggle={() => setRulesExpanded(!rulesExpanded)}
          />
          {rulesExpanded && (
            <div className="mt-2 space-y-1">
              {data.rules.map((rule, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-[11px] py-1 px-2 rounded hover:bg-muted/30"
                >
                  <span className="mt-0.5 shrink-0">
                    {rule.matched ? (
                      <Check size={11} className="text-status-success" />
                    ) : (
                      <Minus size={11} className="text-muted-foreground/40" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <span
                      className={`font-medium ${rule.matched ? "text-status-success" : "text-muted-foreground"}`}
                    >
                      {rule.name}
                    </span>
                    <span className="text-muted-foreground/60 ml-1.5">
                      — {rule.description}
                    </span>
                    {rule.detail && (
                      <div className="text-[10px] text-muted-foreground/50 mt-0.5">
                        {rule.detail}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ▸ Step 3: ML Scoring */}
        <div className="px-4 py-3 border-b border-border/60">
          <SectionHeader
            icon={<Brain size={12} />}
            title="ML Engine Scoring"
            badge={
              <span className="text-[10px] text-muted-foreground/70 ml-1">
                Weights: Performance {(data.weights.fit * 100).toFixed(0)}% · Cost{" "}
                {(data.weights.cost * 100).toFixed(0)}%
              </span>
            }
          />

          {/* Eligible engines table */}
          <div className="mt-3">
            <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mb-1.5 flex items-center gap-1">
              <Check size={9} />
              Eligible engines ({eligibleEngines.length})
            </div>
            <div className="rounded-md border border-border/60 overflow-hidden">
              {/* Table header */}
              <div className="grid grid-cols-[1fr_72px_62px_72px_40px_72px_72px_60px_24px] gap-0 px-3 py-1.5 bg-muted/30 border-b border-border/40 text-[10px] text-muted-foreground/70 uppercase tracking-wider">
                <span>Engine</span>
                <span className="text-right">Predicted</span>
                <span className="text-right flex items-center justify-end gap-0.5">
                  <Clock size={8} /> Cold
                </span>
                <span className="text-right">Est. Time</span>
                <span className="text-right">Tier</span>
                <span className="text-right text-blue-400/80">
                  <Zap size={8} className="inline -mt-px" /> Perf
                </span>
                <span className="text-right text-amber-400/80">
                  <DollarSign size={8} className="inline -mt-px" /> Cost
                </span>
                <span className="text-right font-semibold">Score</span>
                <span></span>
              </div>
              {/* Engine rows */}
              {eligibleEngines.map((eng) => (
                <div
                  key={eng.engineId}
                  className={`grid grid-cols-[1fr_72px_62px_72px_40px_72px_72px_60px_24px] gap-0 px-3 py-2 text-[11px] border-b border-border/20 last:border-b-0 ${
                    eng.isWinner
                      ? "bg-primary/5"
                      : "hover:bg-muted/20"
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`w-[6px] h-[6px] rounded-full shrink-0 ${
                        eng.engineType === "duckdb"
                          ? "bg-emerald-500"
                          : "bg-blue-500"
                      }`}
                    />
                    <span className="font-medium text-foreground">
                      {eng.displayName}
                    </span>
                    <StatePill state={eng.runtimeState} />
                  </span>
                  <span className="text-right text-muted-foreground font-mono">
                    {formatMs(eng.predictedMs)}
                  </span>
                  <span
                    className={`text-right font-mono ${
                      eng.coldStartMs === 0
                        ? "text-status-success"
                        : "text-status-warning"
                    }`}
                  >
                    {eng.coldStartMs === 0 ? "warm" : formatMs(eng.coldStartMs)}
                  </span>
                  <span className="text-right text-foreground font-mono font-medium">
                    {formatMs(eng.totalMs)}
                  </span>
                  <span className="text-right text-muted-foreground">
                    {eng.costTier}
                  </span>
                  <span className="text-right font-mono text-blue-400/90">
                    {eng.latencyContribution.toFixed(3)}
                  </span>
                  <span className="text-right font-mono text-amber-400/90">
                    {eng.costContribution.toFixed(3)}
                  </span>
                  <span
                    className={`text-right font-mono font-semibold ${
                      eng.isWinner ? "text-primary" : "text-foreground"
                    }`}
                  >
                    {eng.weightedScore.toFixed(3)}
                  </span>
                  <span className="text-right">
                    {eng.isWinner && (
                      <Trophy size={12} className="text-primary inline-block" />
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Filtered engines */}
          {filteredEngines.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Filter size={9} />
                Filtered out ({filteredEngines.length})
              </div>
              <div className="space-y-0.5">
                {filteredEngines.map((eng) => (
                  <div
                    key={eng.engineId}
                    className="flex items-center justify-between text-[11px] px-3 py-1.5 rounded bg-muted/20 text-muted-foreground/60"
                  >
                    <span className="flex items-center gap-1.5">
                      <span
                        className={`w-[6px] h-[6px] rounded-full shrink-0 opacity-40 ${
                          eng.engineType === "duckdb"
                            ? "bg-emerald-500"
                            : "bg-blue-500"
                        }`}
                      />
                      <span>{eng.displayName}</span>
                      <StatePill state={eng.runtimeState} />
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="font-mono text-[10px]">
                        {formatMs(eng.predictedMs)} predicted
                      </span>
                      <span className="text-[10px] italic">
                        {eng.filterReason}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ▸ Step 4: Result */}
        <div className="px-4 py-3">
          <SectionHeader icon={<Zap size={12} />} title="Result" />
          <div className="mt-2 flex items-center gap-4 text-[11px]">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-[8px] h-[8px] rounded-full ${
                  winner?.engineType === "duckdb"
                    ? "bg-emerald-500"
                    : "bg-blue-500"
                }`}
              />
              <span className="font-semibold text-foreground">
                {data.winnerDisplayName}
              </span>
            </div>
            <span className="text-muted-foreground">
              via {data.stage.replace(/_/g, " ")}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="font-mono text-foreground font-medium">
              {formatMs(data.executionTimeMs)}
            </span>
            <span className="text-status-success flex items-center gap-0.5">
              <Check size={10} /> Success
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RoutingDecisionView;
