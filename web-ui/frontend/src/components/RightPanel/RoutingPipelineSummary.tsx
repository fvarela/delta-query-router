import React, { useState, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import {
  Shield,
  GitBranch,
  Brain,
  Scale,
  TrendingUp,
  HardDrive,
  ArrowDown,
  X as XIcon,
  Check,
  AlertTriangle,
} from "lucide-react";

/**
 * RoutingPipelineSummary — a compact, dynamic diagram at the bottom of the
 * Routing tab that visualises the current routing pipeline state at a glance.
 *
 * Each stage box shows:
 *   - An icon + abbreviated label
 *   - A live count / status badge
 *   - Color coding: green (healthy), amber (needs attention), gray (inactive)
 *
 * Only rendered in multi-engine (Smart Routing) mode.
 */

/* ── Stage definitions ─────────────────────────────────────────── */

interface StageStatus {
  label: string;
  badge: string;          // e.g. "2", "1 active", "✕"
  color: "green" | "amber" | "gray";
  icon: React.ReactNode;
}

const ICON_SIZE = 11;

/* ── Component ─────────────────────────────────────────────────── */

export const RoutingPipelineSummary: React.FC = () => {
  const {
    engines,
    enabledEngineIds,
    connectedWorkspace,
    models,
    activeModelId,
    routingSettings,
    storageProbes,
    runMode,
  } = useApp();

  const [systemRuleCount, setSystemRuleCount] = useState(0);
  const [customRuleCount, setCustomRuleCount] = useState(0);

  // Fetch rule counts (these are loaded separately, not in context)
  useEffect(() => {
    mockApi.getRoutingRules().then((rules) => {
      setSystemRuleCount(rules.filter((r) => r.is_system).length);
      setCustomRuleCount(rules.filter((r) => !r.is_system).length);
    });
  }, []);

  // Only show in smart routing mode
  if (runMode !== "multi") return null;

  // ── Compute per-stage statuses ──────────────────────────────

  // Visible enabled engine count
  const visibleEnabled = engines.filter((e) => {
    if (!enabledEngineIds.has(e.id)) return false;
    if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
    return true;
  });

  // Engine string IDs for compatibility check (same logic as MLModelSelector)
  const enabledEngineStringIds = visibleEnabled.map((e) => {
    if (e.engine_type === "duckdb") {
      return `duckdb:${e.config.memory_gb}gb-${e.config.cpu_count}cpu`;
    }
    return `databricks:serverless-${e.display_name.split(" ").pop()?.toLowerCase()}`;
  });

  const isModelCompatible = (linkedEngines: string[]) =>
    enabledEngineStringIds.every((ee) => linkedEngines.includes(ee));

  const activeModel = activeModelId != null ? models.find((m) => m.id === activeModelId) : null;
  const activeIsCompatible = activeModel ? isModelCompatible(activeModel.linked_engines) : false;

  // Priority label
  const priorityLabel =
    routingSettings.latency_weight >= 0.7
      ? "Fast"
      : routingSettings.latency_weight <= 0.3
      ? "Low Cost"
      : "Balanced";

  // Storage probe count
  const uniqueLocations = new Set(storageProbes.map((p) => p.storage_location)).size;
  const hasDuckDb = engines.some(
    (e) => e.engine_type === "duckdb" && enabledEngineIds.has(e.id)
  );

  const stages: StageStatus[] = [
    // 1. System Rules
    {
      label: "System Rules",
      badge: `${systemRuleCount}`,
      color: systemRuleCount > 0 ? "green" : "gray",
      icon: <Shield size={ICON_SIZE} />,
    },
    // 2. If-Then Rules
    {
      label: "If-Then Rules",
      badge: `${customRuleCount}`,
      color: customRuleCount > 0 ? "green" : "gray",
      icon: <GitBranch size={ICON_SIZE} />,
    },
    // 3. ML Model
    {
      label: "ML Model",
      badge: activeIsCompatible ? "Active" : "None",
      color: activeIsCompatible ? "green" : "amber",
      icon: <Brain size={ICON_SIZE} />,
    },
    // 4. Cost vs Latency Priority
    {
      label: "Priority",
      badge: priorityLabel,
      color: activeIsCompatible ? "green" : "gray",
      icon: <Scale size={ICON_SIZE} />,
    },
    // 5. Running Engine Bonus
    {
      label: "Bonus",
      badge: `${routingSettings.running_bonus_duckdb}/${routingSettings.running_bonus_databricks}`,
      color:
        routingSettings.running_bonus_duckdb === 0 && routingSettings.running_bonus_databricks === 0
          ? "gray"
          : "green",
      icon: <TrendingUp size={ICON_SIZE} />,
    },
    // 6. Storage Latency
    ...(hasDuckDb
      ? [
          {
            label: "Storage",
            badge: uniqueLocations > 0 ? `${uniqueLocations}` : "0",
            color: (uniqueLocations > 0 ? "green" : "amber") as StageStatus["color"],
            icon: <HardDrive size={ICON_SIZE} />,
          },
        ]
      : []),
  ];

  /* ── Colour mappings ──────────────────────────────────────── */

  const boxClasses: Record<StageStatus["color"], string> = {
    green: "border-emerald-500/40 bg-emerald-500/8 text-emerald-400",
    amber: "border-amber-500/40 bg-amber-500/8 text-amber-400",
    gray: "border-border bg-muted/30 text-muted-foreground",
  };

  const badgeClasses: Record<StageStatus["color"], string> = {
    green: "bg-emerald-500/15 text-emerald-500",
    amber: "bg-amber-500/15 text-amber-500",
    gray: "bg-muted text-muted-foreground",
  };

  return (
    <div className="px-3 py-2.5">
      <div className="rounded-lg border border-border bg-muted/10 px-3 py-2.5">
        <p className="text-[9px] text-muted-foreground mb-2 uppercase tracking-wider font-medium">
          Routing Pipeline
        </p>

        <div className="flex flex-col items-center gap-0">
          {stages.map((stage, idx) => (
            <React.Fragment key={stage.label}>
              {idx > 0 && (
                <ArrowDown size={9} className="text-muted-foreground/40 my-[-1px]" />
              )}
              <div
                className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded border text-[10px] transition-colors ${boxClasses[stage.color]}`}
              >
                <span className="shrink-0 opacity-70">{stage.icon}</span>
                <span className="font-medium flex-1 min-w-0 truncate">{stage.label}</span>
                <span
                  className={`text-[9px] font-semibold px-1.5 py-0.5 rounded shrink-0 ${badgeClasses[stage.color]}`}
                >
                  {stage.badge}
                </span>
              </div>
            </React.Fragment>
          ))}

          {/* Output indicator */}
          <ArrowDown size={9} className="text-muted-foreground/40 my-[-1px]" />
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground font-medium py-1">
            <span>▸</span>
            <span>Selected Engine</span>
          </div>
        </div>
      </div>
    </div>
  );
};
