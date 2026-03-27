import React, { useState, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { api } from "@/lib/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { RoutingRule } from "@/types";
import {
  Shield,
  GitBranch,
  Brain,
  Calculator,
  Trash2,
  Plus,
  X,
  ArrowUp,
  ArrowDown as ArrowDownIcon,
  Zap,
  RotateCcw,
  ChevronRight,
} from "lucide-react";

/* ════════════════════════════════════════════════════════════════
   Stage identifiers
   ════════════════════════════════════════════════════════════════ */

type StageId = "system" | "rules" | "ml" | "scoring";
// Sub-stages within Scoring
type ScoringSubId = "priority" | "bonus" | "storage";
type SelectableId = StageId | ScoringSubId;

/* ════════════════════════════════════════════════════════════════
   Shared helpers
   ════════════════════════════════════════════════════════════════ */

// System rules
const CONDITION_LABELS: Record<string, string> = {
  table_type: "Table type",
  has_governance: "Governance",
  data_source_format: "Format",
  external_access: "External access",
};

// If-Then rules
const conditionOptions = [
  { value: "table_name_pattern", label: "Table Name Pattern" },
  { value: "complexity_gt", label: "Complexity >" },
  { value: "table_type", label: "Table Type" },
  { value: "has_governance", label: "Has Governance" },
  { value: "external_access", label: "External Access" },
];
const comparatorOptions = [
  { value: "greater_than", label: "Greater Than" },
  { value: "less_than", label: "Less Than" },
  { value: "equals", label: "Equal To" },
];
const targetOptions = [
  { value: "duckdb", label: "DuckDB" },
  { value: "databricks", label: "Databricks" },
];
const parseRule = (r: RoutingRule) => {
  const condLabel = conditionOptions.find(c => c.value === r.condition_type)?.label ?? r.condition_type;
  let comparator = "Equal To";
  let value = r.condition_value;
  if (r.condition_value.includes(":")) {
    const [op, ...rest] = r.condition_value.split(":");
    const compOption = comparatorOptions.find(c => c.value === op);
    if (compOption) { comparator = compOption.label; value = rest.join(":"); }
  }
  const targetLabel = targetOptions.find(t => t.value === r.target_engine)?.label ?? r.target_engine;
  return { condLabel, comparator, value, targetLabel };
};

// Cost vs Latency Priority
const PRESETS = [
  { label: "Low Cost", latency_weight: 0.2, description: "Prefer cheaper engines" },
  { label: "Balanced", latency_weight: 0.5, description: "Equal weight" },
  { label: "Fast", latency_weight: 0.8, description: "Prefer faster engines" },
] as const;

// Running Engine Bonus
const DEFAULT_DUCKDB = 0.05;
const DEFAULT_DATABRICKS = 0.15;

/* ════════════════════════════════════════════════════════════════
   Node status types
   ════════════════════════════════════════════════════════════════ */

type NodeColor = "green" | "amber" | "gray";

interface NodeMeta {
  id: SelectableId;
  label: string;
  status: string;
  color: NodeColor;
  icon: React.ReactNode;
}

/* ════════════════════════════════════════════════════════════════
   Main component
   ════════════════════════════════════════════════════════════════ */

export const RoutingPipeline: React.FC = () => {
  const {
    engines, enabledEngineIds, connectedWorkspace,
    models, activeModelId, setActiveModelId, reloadModels,
    routingSettings, updateRoutingSettings,
    storageProbes, runStorageProbes, probesRunning,
    runMode, setPanelMode,
  } = useApp();

  const [activePanel, setActivePanel] = useState<SelectableId | null>(null);

  // Rule data (loaded once)
  const [allRules, setAllRules] = useState<RoutingRule[]>([]);
  useEffect(() => { api.get<RoutingRule[]>("/api/routing/rules").then(setAllRules).catch(() => {}); }, []);
  const systemRules = allRules.filter(r => r.is_system);
  const customRules = allRules.filter(r => !r.is_system).sort((a, b) => a.priority - b.priority);

  // If-Then Rules modal / form state
  const [showRulesModal, setShowRulesModal] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleteRuleId, setDeleteRuleId] = useState<number | null>(null);
  const [newCondition, setNewCondition] = useState("table_name_pattern");
  const [newComparator, setNewComparator] = useState("equals");
  const [newValue, setNewValue] = useState("");
  const [newTarget, setNewTarget] = useState("duckdb");

  const loadRules = async () => { setAllRules(await api.get<RoutingRule[]>("/api/routing/rules")); };
  const handleDeleteRule = async () => {
    if (deleteRuleId === null) return;
    try {
      await api.del(`/api/routing/rules/${deleteRuleId}`);
      await loadRules();
    } catch (e: any) {
      console.error("Failed to delete rule:", e?.message);
    }
    setDeleteRuleId(null);
  };
  const handleAddRule = async () => {
    if (!newValue.trim()) return;
    const maxPriority = Math.max(0, ...customRules.map(r => r.priority));
    try {
      await api.post<RoutingRule>("/api/routing/rules", {
        priority: maxPriority + 1, condition_type: newCondition,
        condition_value: newComparator === "equals" ? newValue : `${newComparator}:${newValue}`,
        target_engine: newTarget,
      });
      await loadRules(); setShowAddForm(false); setNewValue("");
    } catch (e: any) {
      console.error("Failed to create rule:", e?.message);
    }
  };
  const handleMoveUp = async (idx: number) => {
    if (idx === 0) return;
    const cur = customRules[idx], above = customRules[idx - 1];
    try {
      await api.put<RoutingRule>(`/api/routing/rules/${cur.id}`, { priority: above.priority });
      await api.put<RoutingRule>(`/api/routing/rules/${above.id}`, { priority: cur.priority });
      await loadRules();
    } catch (e: any) {
      console.error("Failed to reorder rules:", e?.message);
    }
  };
  const handleMoveDown = async (idx: number) => {
    if (idx === customRules.length - 1) return;
    const cur = customRules[idx], below = customRules[idx + 1];
    try {
      await api.put<RoutingRule>(`/api/routing/rules/${cur.id}`, { priority: below.priority });
      await api.put<RoutingRule>(`/api/routing/rules/${below.id}`, { priority: cur.priority });
      await loadRules();
    } catch (e: any) {
      console.error("Failed to reorder rules:", e?.message);
    }
  };

  // ML Models state
  const [deletingModelId, setDeletingModelId] = useState<number | null>(null);
  const [detailModelId, setDetailModelId] = useState<number | null>(null);

  const enabledEngineStringIds = engines
    .filter(e => {
      if (!enabledEngineIds.has(e.id)) return false;
      if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
      return true;
    })
    .map(e => e.engine_type === "duckdb"
      ? `duckdb:${e.config.memory_gb}gb-${e.config.cpu_count}cpu`
      : `databricks:serverless-${e.display_name.split(" ").pop()?.toLowerCase()}`
    );

  const isModelCompatible = (linked: string[]) => enabledEngineStringIds.every(ee => linked.includes(ee));
  const compatibleCount = models.filter(m => isModelCompatible(m.linked_engines)).length;
  const activeModel = activeModelId != null ? models.find(m => m.id === activeModelId) : null;
  const activeIsCompatible = activeModel ? isModelCompatible(activeModel.linked_engines) : false;

  const handleActivateModel = async (id: number) => {
    if (activeModelId === id) { await mockApi.deactivateModel(id); setActiveModelId(null); }
    else { await mockApi.activateModel(id); setActiveModelId(id); }
    await reloadModels();
  };
  const handleDeleteModel = async (id: number) => {
    setDeletingModelId(id);
    try { await mockApi.deleteModel(id); if (activeModelId === id) setActiveModelId(null); await reloadModels(); }
    finally { setDeletingModelId(null); }
  };
  const detailModel = detailModelId != null ? models.find(m => m.id === detailModelId) : null;

  // Cost vs Latency Priority
  const handleSelectPreset = (lw: number) => updateRoutingSettings({ latency_weight: lw, cost_weight: 1 - lw });
  const activePresetIdx = PRESETS.reduce((best, p, i) => {
    return Math.abs(p.latency_weight - routingSettings.latency_weight) < Math.abs(PRESETS[best].latency_weight - routingSettings.latency_weight) ? i : best;
  }, 0);
  const priorityLabel = PRESETS[activePresetIdx].label;

  // Running Engine Bonus
  const duckdbBonus = routingSettings.running_bonus_duckdb;
  const databricksBonus = routingSettings.running_bonus_databricks;
  const isBonusDefault = duckdbBonus === DEFAULT_DUCKDB && databricksBonus === DEFAULT_DATABRICKS;
  const handleDuckdbChange = (v: string) => { const n = parseFloat(v); if (!isNaN(n) && n >= 0 && n <= 1) updateRoutingSettings({ running_bonus_duckdb: n }); };
  const handleDatabricksChange = (v: string) => { const n = parseFloat(v); if (!isNaN(n) && n >= 0 && n <= 1) updateRoutingSettings({ running_bonus_databricks: n }); };
  const handleResetBonus = () => updateRoutingSettings({ running_bonus_duckdb: DEFAULT_DUCKDB, running_bonus_databricks: DEFAULT_DATABRICKS });

  // Storage Latency
  const uniqueLocations = new Set(storageProbes.map(p => p.storage_location)).size;
  const formatLatency = (ms: number) => `${ms.toFixed(0)} ms`;
  const formatBytes = (b: number) => b < 1024 * 1024 ? `${(b / 1024).toFixed(0)} KB` : `${(b / (1024 * 1024)).toFixed(1)} MB`;
  const formatTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  /* ── Build node metadata ──────────────────────────────────── */

  const ICON_SZ = 13;

  const mainNodes: NodeMeta[] = [
    {
      id: "system", label: "System Rules",
      status: `${systemRules.length} rule${systemRules.length !== 1 ? "s" : ""}`,
      color: systemRules.length > 0 ? "green" : "gray",
      icon: <Shield size={ICON_SZ} />,
    },
    {
      id: "rules", label: "If-Then Rules",
      status: customRules.length > 0 ? `${customRules.length} rule${customRules.length !== 1 ? "s" : ""}` : "none",
      color: customRules.length > 0 ? "green" : "gray",
      icon: <GitBranch size={ICON_SZ} />,
    },
    {
      id: "ml", label: "ML Models",
      status: activeIsCompatible ? "Active" : models.length > 0 ? `${compatibleCount}/${models.length}` : "None",
      color: activeIsCompatible ? "green" : models.length > 0 ? "amber" : "gray",
      icon: <Brain size={ICON_SZ} />,
    },
    {
      id: "scoring", label: "Scoring & Select",
      status: activeIsCompatible ? priorityLabel : "Rules only",
      color: activeIsCompatible ? "green" : "gray",
      icon: <Calculator size={ICON_SZ} />,
    },
  ];

  // Sub-nodes within Scoring
  const scoringSubNodes: { id: ScoringSubId; label: string; status: string; color: NodeColor }[] = [
    { id: "priority", label: "Priority", status: priorityLabel, color: activeIsCompatible ? "green" : "gray" },
    { id: "bonus", label: "Bonus", status: `${duckdbBonus}/${databricksBonus}`, color: duckdbBonus === 0 && databricksBonus === 0 ? "gray" : "green" },
    { id: "storage" as ScoringSubId, label: "Storage", status: uniqueLocations > 0 ? `${uniqueLocations} loc` : "none", color: (uniqueLocations > 0 ? "green" : "amber") as NodeColor },
  ];

  const handleNodeClick = (id: SelectableId) => setActivePanel(prev => prev === id ? null : id);

  if (runMode !== "multi") return null;

  /* ── Color helpers ────────────────────────────────────────── */

  const dotColor = (c: NodeColor) => {
    switch (c) {
      case "green": return "bg-emerald-500";
      case "amber": return "bg-amber-500";
      case "gray": return "bg-muted-foreground/40";
    }
  };

  const lineColor = (c: NodeColor) => {
    switch (c) {
      case "green": return "border-emerald-500/50";
      case "amber": return "border-amber-500/50";
      case "gray": return "border-muted-foreground/20";
    }
  };

  /* ── Render ──────────────────────────────────────────────── */

  return (
    <>
      <div className="px-3 pt-2 pb-1 text-[12px]">
        {/* Header */}
        <p className="text-[9px] text-muted-foreground mb-1.5 uppercase tracking-wider font-medium">
          Routing Pipeline
        </p>

        {/* ─── Timeline diagram ─── */}
        <div className="relative ml-[7px]">
          {/* Continuous vertical line behind nodes */}
          <div className="absolute left-[5px] top-[5px] bottom-[5px] w-px bg-border" />

          {mainNodes.map((node, idx) => {
            const isSelected = activePanel === node.id;
            const isLast = idx === mainNodes.length - 1;
            const isScoring = node.id === "scoring";

            return (
              <div key={node.id} className={idx > 0 ? "mt-0" : ""}>
                {/* ── Main node row ── */}
                <button
                  onClick={() => handleNodeClick(node.id)}
                  className={`relative flex items-center gap-2 w-full text-left py-[5px] pl-0 pr-1 group transition-colors rounded-r-sm
                    ${isSelected ? "bg-primary/5" : "hover:bg-muted/30"}`}
                >
                  {/* Dot on timeline */}
                  <div className={`relative z-10 w-[11px] h-[11px] rounded-full border-2 shrink-0
                    ${isSelected ? "border-primary bg-primary/30" : `border-transparent ${dotColor(node.color)}`}`}
                  />
                  {/* Icon */}
                  <span className={`shrink-0 ${isSelected ? "text-primary" : "text-muted-foreground"}`}>
                    {node.icon}
                  </span>
                  {/* Label */}
                  <span className={`flex-1 text-[11px] font-medium truncate
                    ${isSelected ? "text-primary" : "text-foreground"}`}>
                    {node.label}
                  </span>
                  {/* Status text */}
                  <span className={`text-[10px] shrink-0
                    ${isSelected ? "text-primary/70" : "text-muted-foreground"}`}>
                    {node.status}
                  </span>
                </button>

                {/* ── Scoring sub-nodes ── */}
                {isScoring && (
                  <div className="ml-[22px] border-l border-dashed border-muted-foreground/20 pl-2 py-0.5">
                    {scoringSubNodes.map(sub => {
                      const subSelected = activePanel === sub.id;
                      return (
                        <button
                          key={sub.id}
                          onClick={() => handleNodeClick(sub.id)}
                          className={`flex items-center gap-1.5 w-full text-left py-[3px] pr-1 rounded-sm transition-colors
                            ${subSelected ? "bg-primary/5" : "hover:bg-muted/30"}`}
                        >
                          <div className={`w-[7px] h-[7px] rounded-full shrink-0
                            ${subSelected ? "bg-primary/60" : dotColor(sub.color)}`}
                          />
                          <span className={`text-[10px] flex-1
                            ${subSelected ? "text-primary font-medium" : "text-muted-foreground"}`}>
                            {sub.label}
                          </span>
                          <span className={`text-[9px] shrink-0
                            ${subSelected ? "text-primary/60" : "text-muted-foreground/70"}`}>
                            {sub.status}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Spacing between nodes (except last) */}
                {!isLast && <div className="h-px" />}
              </div>
            );
          })}

          {/* Terminal node: Selected Engine */}
          <div className="relative flex items-center gap-2 py-[5px]">
            <div className="relative z-10 w-[11px] h-[11px] rounded-sm bg-primary/60 shrink-0" style={{ clipPath: "polygon(0 0, 100% 50%, 0 100%)" }} />
            <ChevronRight size={11} className="text-primary/50 shrink-0 -ml-1" />
            <span className="text-[10px] text-muted-foreground font-medium">Selected Engine</span>
          </div>
        </div>

        {/* ─── Detail area ─── */}
        <div className="mt-2 border border-border rounded-md bg-card/30 min-h-[80px]">
          {/* Detail header */}
          <div className="px-3 py-1.5 border-b border-border/60 flex items-center justify-between">
            <span className="text-[10px] font-semibold text-foreground">
              {activePanel ? getDetailTitle(activePanel) : "Pipeline Overview"}
            </span>
            {activePanel && (
              <button
                onClick={() => setActivePanel(null)}
                className="text-muted-foreground hover:text-foreground p-0.5"
              >
                <X size={11} />
              </button>
            )}
          </div>

          {/* Detail content */}
          <div className="px-3 py-2 text-[11px]">
            {renderDetail(activePanel)}
          </div>
        </div>
      </div>

      {/* ── Modals ── */}
      {showRulesModal && <IfThenRulesModal />}
      {detailModel && <MLModelDetailModal />}
      <ConfirmDialog
        open={deleteRuleId !== null}
        title="Delete Rule"
        description="Delete this routing rule?"
        onConfirm={handleDeleteRule}
        onCancel={() => setDeleteRuleId(null)}
        destructive
      />
    </>
  );

  /* ══════════════════════════════════════════════════════════════
     Detail panel renderers
     ══════════════════════════════════════════════════════════════ */

  function getDetailTitle(id: SelectableId): string {
    switch (id) {
      case "system": return "System Rules";
      case "rules": return "If-Then Rules";
      case "ml": return "ML Models";
      case "scoring": return "Scoring & Engine Selection";
      case "priority": return "Cost vs Latency Priority";
      case "bonus": return "Running Engine Bonus";
      case "storage": return "Storage Latency";
    }
  }

  function renderDetail(id: SelectableId | null) {
    if (id === null) return <OverviewDetail />;
    switch (id) {
      case "system": return <SystemRulesDetail />;
      case "rules": return <IfThenRulesDetail />;
      case "ml": return <MLModelsDetail />;
      case "scoring": return <ScoringOverviewDetail />;
      case "priority": return <PriorityDetail />;
      case "bonus": return <BonusDetail />;
      case "storage": return <StorageDetail />;
    }
  }

  /* ── Overview (default, no stage selected) ── */
  function OverviewDetail() {
    const hasModel = activeIsCompatible;
    const ruleCount = systemRules.length + customRules.length;

    return (
      <div className="space-y-2 text-[11px] text-muted-foreground">
        <p>
          Queries pass through the pipeline top to bottom. Each stage can short-circuit
          and force a specific engine, or pass the query to the next stage.
        </p>
        <div className="space-y-1">
          <div className="flex items-start gap-2">
            <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${ruleCount > 0 ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
            <span><span className="text-foreground font-medium">Rules</span> — {systemRules.length} system + {customRules.length} custom. Hard constraints evaluated first (writes, governance, table formats).</span>
          </div>
          <div className="flex items-start gap-2">
            <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${hasModel ? "bg-emerald-500" : models.length > 0 ? "bg-amber-500" : "bg-muted-foreground/40"}`} />
            <span><span className="text-foreground font-medium">ML Models</span> — {hasModel ? "Active model predicts latency & cost per engine." : models.length > 0 ? `${models.length} model${models.length !== 1 ? "s" : ""} available, none active.` : "No models trained. Routing uses rules only."}</span>
          </div>
          <div className="flex items-start gap-2">
            <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${hasModel ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
            <span><span className="text-foreground font-medium">Scoring</span> — {hasModel ? `Weighted scoring (${priorityLabel}) with running-engine bonus and I/O latency adjustment.` : "Inactive without an ML model. Activate a model to enable weighted scoring."}</span>
          </div>
        </div>
        <p className="text-[10px] italic">Click any pipeline stage above to view details and settings.</p>
      </div>
    );
  }

  /* ── System Rules detail ── */
  function SystemRulesDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          Built-in constraints applied first. These cannot be edited — they enforce
          mandatory routing (e.g. writes, views, governed tables to Databricks).
        </p>
        {systemRules.length === 0 ? (
          <p className="text-muted-foreground italic">No system rules loaded.</p>
        ) : (
          <div className="space-y-0.5">
            {systemRules.map(r => {
              const condLabel = CONDITION_LABELS[r.condition_type] ?? r.condition_type;
              const target = r.target_engine === "databricks" ? "Databricks" : "DuckDB";
              return (
                <div key={r.id} className="text-muted-foreground truncate">
                  {condLabel} = <span className="text-foreground font-medium">{r.condition_value}</span>{" "}
                  &rarr; {target}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  /* ── If-Then Rules detail ── */
  function IfThenRulesDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          User-defined rules evaluated in priority order after system rules.
          If a rule matches, the query is routed to its target engine.
        </p>
        {customRules.length === 0 ? (
          <p className="text-muted-foreground italic">No custom rules defined.</p>
        ) : (
          <div className="space-y-0.5">
            {customRules.map(r => {
              const { condLabel, comparator, value, targetLabel } = parseRule(r);
              return (
                <div key={r.id} className="text-muted-foreground truncate">
                  {condLabel} {comparator} <span className="text-foreground font-medium">{value}</span> &rarr; {targetLabel}
                </div>
              );
            })}
          </div>
        )}
        <button
          onClick={() => setShowRulesModal(true)}
          className="text-[10px] text-primary hover:text-primary/80 font-medium"
        >
          Edit Rules...
        </button>
      </div>
    );
  }

  /* ── ML Models detail ── */
  function MLModelsDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          ML models predict per-engine latency and cost from query features.
          Activate a compatible model to enable scored routing.
        </p>
        {models.length === 0 ? (
          <p className="text-muted-foreground italic">
            No models trained yet.
          </p>
        ) : (
          <div className="divide-y divide-border/50 -mx-3">
            {models.map(m => {
              const compatible = isModelCompatible(m.linked_engines);
              const isActive = activeModelId === m.id;
              const isDeleting = deletingModelId === m.id;
              return (
                <div key={m.id} className={`px-3 py-1.5 ${!compatible ? "opacity-40" : ""} ${isDeleting ? "opacity-50" : ""}`}>
                  <div className="flex items-center gap-2">
                    <input type="radio" name="active-model-pipe" checked={isActive}
                      disabled={!compatible || isDeleting} onChange={() => handleActivateModel(m.id)}
                      className="accent-primary shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-foreground font-medium truncate">Model #{m.id}</span>
                        {isActive && <span className="text-[9px] bg-primary/20 text-primary px-1 rounded">Active</span>}
                        {!compatible && <span className="text-[9px] text-status-warning">Incompatible</span>}
                      </div>
                      <div className="text-[10px] text-muted-foreground">
                        {m.linked_engines.length} engines · {m.benchmark_count ?? 0} benchmarks
                        <span className="mx-1">·</span>
                        <button onClick={e => { e.stopPropagation(); setDetailModelId(m.id); }}
                          className="text-primary/70 hover:text-primary">View Details</button>
                      </div>
                    </div>
                    <button onClick={() => handleDeleteModel(m.id)} disabled={isDeleting}
                      className="text-muted-foreground hover:text-red-500 shrink-0 p-0.5" title="Delete model">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {models.length > 0 && !activeIsCompatible && (
          <p className="text-[10px] text-muted-foreground">
            {compatibleCount > 0
              ? "Select a model to enable ML-based routing. Without one, routing uses rules only."
              : "No models cover all selected engines. Train a new model or adjust engine selection."}
          </p>
        )}
        <button onClick={() => setPanelMode("train")}
          className="flex items-center gap-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors">
          <Zap size={11} className="text-amber-500/70" />
          <span>Train New Model...</span>
        </button>
      </div>
    );
  }

  /* ── Scoring overview (clicking the main "Scoring" node) ── */
  function ScoringOverviewDetail() {
    return (
      <div className="space-y-2 text-muted-foreground">
        <p className="text-[10px]">
          When an ML model is active, each engine receives a weighted score combining
          predicted latency and estimated cost. The engine with the lowest score is selected.
        </p>
        <div className="space-y-1 text-[10px]">
          <div className="flex items-center gap-2">
            <span className="text-foreground font-medium w-[60px] shrink-0">Priority</span>
            <span>{priorityLabel} ({(routingSettings.latency_weight * 100).toFixed(0)}% latency / {(routingSettings.cost_weight * 100).toFixed(0)}% cost)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-foreground font-medium w-[60px] shrink-0">Bonus</span>
            <span>DuckDB {duckdbBonus} · Databricks {databricksBonus}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-foreground font-medium w-[60px] shrink-0">Storage</span>
            <span>{uniqueLocations > 0 ? `${uniqueLocations} location${uniqueLocations !== 1 ? "s" : ""} probed` : "No probe data — run probes to measure I/O latency"}</span>
          </div>
        </div>
        {!activeIsCompatible && (
          <p className="text-[10px] italic">
            Scoring is inactive — activate an ML model to enable weighted engine selection.
          </p>
        )}
        <p className="text-[10px] italic">
          Click the sub-items (Priority, Bonus, Storage) in the diagram to configure each parameter.
        </p>
      </div>
    );
  }

  /* ── Cost vs Latency Priority detail ── */
  function PriorityDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          Controls the trade-off between speed and cost in the scoring formula.
          Higher latency weight favors faster engines; lower weight favors cheaper ones.
        </p>
        <div className="flex gap-1">
          {PRESETS.map((preset, idx) => {
            const isActive = idx === activePresetIdx;
            return (
              <button key={preset.label} onClick={() => handleSelectPreset(preset.latency_weight)}
                title={preset.description}
                className={`flex-1 px-1.5 py-1.5 rounded text-[10px] font-medium border text-center transition-colors ${
                  isActive ? "bg-primary/10 text-primary border-primary" : "bg-muted/30 text-muted-foreground border-border hover:bg-muted/60"
                }`}>
                {preset.label}
              </button>
            );
          })}
        </div>
        {activeModelId == null && (
          <p className="text-[10px] text-muted-foreground italic">
            No ML model active — priority weighting has no effect until a model is selected.
          </p>
        )}
      </div>
    );
  }

  /* ── Running Engine Bonus detail ── */
  function BonusDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          Running engines get a score reduction (bonus), nudging the router toward
          already-running engines to avoid cold-start delays and billing commitments.
        </p>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <label className="text-muted-foreground w-[72px] shrink-0">DuckDB</label>
            <input type="number" min={0} max={1} step={0.01} value={duckdbBonus}
              onChange={e => handleDuckdbChange(e.target.value)}
              className="w-[64px] px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground text-right" />
            <span className="text-[9px] text-muted-foreground">0 = off · 1 = max</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-muted-foreground w-[72px] shrink-0">Databricks</label>
            <input type="number" min={0} max={1} step={0.01} value={databricksBonus}
              onChange={e => handleDatabricksChange(e.target.value)}
              className="w-[64px] px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground text-right" />
          </div>
        </div>
        {!isBonusDefault && (
          <button onClick={handleResetBonus}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors">
            <RotateCcw size={10} /> <span>Reset to Defaults</span>
          </button>
        )}
      </div>
    );
  }

  /* ── Storage Latency detail ── */
  function StorageDetail() {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground text-[10px]">
          I/O latency from DuckDB to cloud storage, measured per location.
          Factored into latency predictions to make benchmarks portable across deployments.
        </p>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground text-[10px]">
            {uniqueLocations > 0 ? `${uniqueLocations} location${uniqueLocations !== 1 ? "s" : ""} probed` : "No probe data"}
          </span>
          <button onClick={runStorageProbes} disabled={probesRunning}
            className="px-2 py-0.5 text-[10px] font-medium rounded border border-border hover:bg-muted disabled:opacity-50 text-foreground">
            {probesRunning ? "Running..." : "Run Probes"}
          </button>
        </div>
        {probesRunning && (
          <div className="flex items-center gap-2 py-1">
            <LoadingSpinner size={12} />
            <span className="text-muted-foreground">Probing storage locations...</span>
          </div>
        )}
        {!probesRunning && storageProbes.length === 0 && (
          <p className="text-muted-foreground text-[10px]">
            Click "Run Probes" to measure storage I/O latency.
          </p>
        )}
        {!probesRunning && storageProbes.length > 0 && (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-muted">
                <th className="text-left px-2 py-1 border-b border-border">Location</th>
                <th className="text-right px-2 py-1 border-b border-border">Latency</th>
                <th className="text-right px-2 py-1 border-b border-border">Read</th>
                <th className="text-right px-2 py-1 border-b border-border">At</th>
              </tr>
            </thead>
            <tbody>
              {storageProbes.map(p => (
                <tr key={p.id} className="even:bg-card">
                  <td className="px-2 py-1 border-b border-border text-foreground truncate max-w-[120px]" title={p.storage_location}>
                    {p.storage_location.replace(/^.*:\/\/[^/]+\//, "")}
                  </td>
                  <td className={`px-2 py-1 border-b border-border text-right font-medium ${
                    p.probe_time_ms < 50 ? "text-status-success" : p.probe_time_ms < 150 ? "text-status-warning" : "text-status-error"
                  }`}>
                    {formatLatency(p.probe_time_ms)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-right text-muted-foreground">
                    {formatBytes(p.bytes_read)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-right text-muted-foreground">
                    {formatTime(p.measured_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  /* ══════════════════════════════════════════════════════════════
     Modals
     ══════════════════════════════════════════════════════════════ */

  function IfThenRulesModal() {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-background border border-border rounded-lg shadow-lg w-[500px] max-h-[80vh] flex flex-col text-[12px]">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="font-semibold text-foreground text-[14px]">If-Then Rules ({customRules.length})</span>
            <button onClick={() => setShowRulesModal(false)} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {customRules.length === 0 && !showAddForm ? (
              <div className="text-[11px] text-muted-foreground py-4 text-center">No rules defined. Click "Add Rule" to create one.</div>
            ) : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-muted">
                    <th className="text-left px-2 py-1.5 border-b border-border">Condition</th>
                    <th className="text-left px-2 py-1.5 border-b border-border">Comparator</th>
                    <th className="text-left px-2 py-1.5 border-b border-border">Value</th>
                    <th className="text-left px-2 py-1.5 border-b border-border">Target</th>
                    <th className="w-16 px-1 py-1.5 border-b border-border"></th>
                  </tr>
                </thead>
                <tbody>
                  {customRules.map((r, idx) => {
                    const { condLabel, comparator, value, targetLabel } = parseRule(r);
                    return (
                      <tr key={r.id} className="even:bg-card hover:bg-muted/50">
                        <td className="px-2 py-1.5 border-b border-border text-foreground">{condLabel}</td>
                        <td className="px-2 py-1.5 border-b border-border text-foreground">{comparator}</td>
                        <td className="px-2 py-1.5 border-b border-border text-foreground">{value}</td>
                        <td className="px-2 py-1.5 border-b border-border text-foreground">{targetLabel}</td>
                        <td className="px-1 py-1.5 border-b border-border">
                          <div className="flex items-center gap-0.5">
                            <button disabled={idx === 0} onClick={() => handleMoveUp(idx)} className="text-muted-foreground hover:text-foreground disabled:opacity-30" title="Move up"><ArrowUp size={11} /></button>
                            <button disabled={idx === customRules.length - 1} onClick={() => handleMoveDown(idx)} className="text-muted-foreground hover:text-foreground disabled:opacity-30" title="Move down"><ArrowDownIcon size={11} /></button>
                            <button onClick={() => setDeleteRuleId(r.id)} className="text-muted-foreground hover:text-status-error" title="Delete"><Trash2 size={11} /></button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {showAddForm && (
              <div className="mt-3 p-3 border border-border rounded space-y-2 bg-muted/20">
                <div className="flex gap-2">
                  <select value={newCondition} onChange={e => setNewCondition(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                    {conditionOptions.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                  <select value={newComparator} onChange={e => setNewComparator(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                    {comparatorOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div className="flex gap-2">
                  <input placeholder="Value" value={newValue} onChange={e => setNewValue(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground" />
                  <select value={newTarget} onChange={e => setNewTarget(e.target.value)} className="px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                    {targetOptions.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </div>
                <div className="flex gap-2">
                  <button onClick={handleAddRule} className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px]">Add Rule</button>
                  <button onClick={() => setShowAddForm(false)} className="px-3 py-1 border border-border rounded text-[11px] text-foreground">Cancel</button>
                </div>
              </div>
            )}
          </div>
          <div className="px-4 py-3 border-t border-border flex justify-between shrink-0">
            <button onClick={() => setShowAddForm(!showAddForm)} className="flex items-center gap-1 px-3 py-1.5 bg-primary text-primary-foreground rounded text-[11px] font-medium">
              <Plus size={12} /> Add Rule
            </button>
            <button onClick={() => setShowRulesModal(false)} className="px-3 py-1.5 border border-border rounded text-[11px] text-foreground">Close</button>
          </div>
        </div>
      </div>
    );
  }

  function MLModelDetailModal() {
    if (!detailModel) return null;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-background border border-border rounded-lg shadow-lg w-[420px] max-h-[80vh] flex flex-col text-[12px]">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
            <span className="font-semibold text-foreground text-[14px]">Model #{detailModel.id} — Details</span>
            <button onClick={() => setDetailModelId(null)} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <div className="space-y-1 text-[11px]">
              <p className="text-muted-foreground">Created: {new Date(detailModel.created_at).toLocaleString()}</p>
              <p className="text-muted-foreground">Engines: {detailModel.linked_engines.join(", ")}</p>
              <p className="text-muted-foreground">Benchmarks used: {detailModel.benchmark_count ?? 0}</p>
              {detailModel.training_queries != null && <p className="text-muted-foreground">Training queries: {detailModel.training_queries}</p>}
            </div>
            <div>
              <h4 className="font-semibold text-foreground mb-1.5 flex items-center gap-1.5">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-blue-500/15 text-blue-500">Latency</span> Sub-model
              </h4>
              <div className="bg-muted/30 rounded p-2.5 space-y-1 text-[11px]">
                <p className="text-foreground">R²: <span className="font-medium">{detailModel.latency_model.r_squared.toFixed(3)}</span></p>
                {detailModel.latency_model.mae_ms != null && <p className="text-foreground">MAE: <span className="font-medium">{detailModel.latency_model.mae_ms} ms</span></p>}
                <p className="text-muted-foreground text-[10px]">Path: {detailModel.latency_model.model_path}</p>
              </div>
            </div>
            <div>
              <h4 className="font-semibold text-foreground mb-1.5 flex items-center gap-1.5">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-emerald-500/15 text-emerald-500">Cost</span> Sub-model
              </h4>
              <div className="bg-muted/30 rounded p-2.5 space-y-1 text-[11px]">
                <p className="text-foreground">R²: <span className="font-medium">{detailModel.cost_model.r_squared.toFixed(3)}</span></p>
                {detailModel.cost_model.mae_usd != null && <p className="text-foreground">MAE: <span className="font-medium">${detailModel.cost_model.mae_usd.toFixed(4)}</span></p>}
                <p className="text-muted-foreground text-[10px]">Path: {detailModel.cost_model.model_path}</p>
              </div>
            </div>
          </div>
          <div className="px-4 py-3 border-t border-border flex justify-end shrink-0">
            <button onClick={() => setDetailModelId(null)} className="px-3 py-1.5 border border-border rounded text-[11px] text-foreground">Close</button>
          </div>
        </div>
      </div>
    );
  }
};
