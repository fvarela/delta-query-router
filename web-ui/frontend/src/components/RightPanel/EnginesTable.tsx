import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { Brain, ChevronDown, Cloud, HardDrive, CheckCircle2, FlaskConical, Settings2, Timer, Zap, RefreshCw } from "lucide-react";
import type { EngineCatalogEntry, Model, WarehouseMapping } from "@/types";
import { ModelsDialog } from "./ModelsDialog";
import { api } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";

export const EnginesTable: React.FC = () => {
  const {
    engines,
    routingMode, setRoutingMode,
    singleEngineId, setSingleEngineId,
    activeModelId, setActiveModelId, models,
    enabledEngineIds, toggleEngineEnabled, setAllEnginesEnabled,
    benchmarkEngineIds, toggleBenchmarkEngine,
    warehouseMappings,
  } = useApp();

  // All engines grouped by type for single-engine mode
  // Only show enabled engines.
  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb" && e.enabled);
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql" && e.enabled);

  // Active model for smart routing mode
  const activeModel = models.find(m => m.id === activeModelId);

  // Engines linked to the active model (for smart routing checkboxes)
  const modelEngines = activeModel
    ? engines.filter(e => activeModel.linked_engines.includes(e.id))
    : [];

  // When switching to smart routing with a model, initialize enabledEngineIds to the model's engines
  const handleModelChange = (modelId: number) => {
    setActiveModelId(modelId);
    const model = models.find(m => m.id === modelId);
    if (model) {
      setAllEnginesEnabled(model.linked_engines);
    }
  };

  return (
    <div className="text-[12px]">
      {/* Mode selector — 3-button segmented control */}
      <div className="px-3 py-2.5 border-b border-panel-border">
        <div className="flex rounded-md border border-border overflow-hidden shadow-sm">
          <button
            onClick={() => setRoutingMode("single")}
            className={`flex-1 py-1.5 text-[12px] font-medium transition-colors border-r border-border ${
              routingMode === "single"
                ? "bg-primary text-primary-foreground"
                : "bg-card text-muted-foreground hover:bg-muted/50"
            }`}
          >
            Single Engine
          </button>
          <button
            onClick={() => setRoutingMode("smart")}
            className={`flex-1 py-1.5 text-[12px] font-medium transition-colors border-r border-border ${
              routingMode === "smart"
                ? "bg-primary text-primary-foreground"
                : "bg-card text-muted-foreground hover:bg-muted/50"
            }`}
          >
            Smart Routing
          </button>
          <button
            onClick={() => setRoutingMode("benchmark")}
            className={`flex-1 py-1.5 text-[12px] font-medium transition-colors ${
              routingMode === "benchmark"
                ? "bg-amber-600 text-white"
                : "bg-card text-muted-foreground hover:bg-muted/50"
            }`}
          >
            Benchmarking
          </button>
        </div>
      </div>

      {/* Content depends on mode */}
      {routingMode === "single" ? (
        <SingleEngineView
          duckdbEngines={duckdbEngines}
          databricksEngines={databricksEngines}
          singleEngineId={singleEngineId}
          onSelect={setSingleEngineId}
          warehouseMappings={warehouseMappings}
        />
      ) : routingMode === "smart" ? (
        <SmartRoutingView
          models={models}
          activeModelId={activeModelId}
          onModelChange={handleModelChange}
          modelEngines={modelEngines}
          enabledEngineIds={enabledEngineIds}
          toggleEngineEnabled={toggleEngineEnabled}
          warehouseMappings={warehouseMappings}
        />
      ) : (
        <BenchmarkingView
          duckdbEngines={duckdbEngines}
          databricksEngines={databricksEngines}
          benchmarkEngineIds={benchmarkEngineIds}
          toggleBenchmarkEngine={toggleBenchmarkEngine}
        />
      )}
    </div>
  );
};

/** Get mapped warehouse display name for an engine */
const getWarehouseName = (engineId: string, mappings: WarehouseMapping[]): string | null => {
  const m = mappings.find(w => w.engineId === engineId);
  return m?.warehouseName ?? null;
};

// ---- Single Engine View ----
const formatColdStart = (e: EngineCatalogEntry): string => {
  if (e.lifecycle_mode === "always-on") return "0ms";
  if (e.cold_start_ms == null) return "—";
  return `${(e.cold_start_ms / 1000).toFixed(1)}s`;
};

/** Compact badges showing lifecycle mode + cold start time with optional re-measure */
const EngineInfoBadges: React.FC<{ engine: EngineCatalogEntry; showMeasure?: boolean }> = ({ engine, showMeasure = false }) => {
  const [measuring, setMeasuring] = useState(false);
  const [measured, setMeasured] = useState(false);
  const { reloadEngines } = useApp();
  const isAlwaysOn = engine.lifecycle_mode === "always-on";

  const handleMeasure = async (ev: React.MouseEvent) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (isMockMode() || measuring) return;
    setMeasuring(true);
    try {
      await api.post(`/api/engines/${engine.id}/measure-cold-start`);
      // Poll until measurement completes
      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 3000));
        const data = await api.get<{ cold_start_ms: number | null; measuring?: boolean }>(`/api/engines/${engine.id}/cold-start`);
        if (data?.measuring === false && data?.cold_start_ms != null) break;
      }
      await reloadEngines();
      setMeasured(true);
      setTimeout(() => setMeasured(false), 3000);
    } catch { /* ignore */ }
    setMeasuring(false);
  };

  return (
    <span className="flex items-center gap-1.5 flex-wrap">
      {/* Lifecycle badge */}
      <span className={`inline-flex items-center gap-0.5 text-[9px] font-semibold uppercase tracking-wide ${
        isAlwaysOn ? "text-emerald-600" : "text-amber-600"
      }`}>
        {isAlwaysOn ? <Zap size={8} /> : <Timer size={8} />}
        {isAlwaysOn ? "always-on" : "on-demand"}
      </span>
      {/* Cold start pill */}
      <span className={`inline-flex items-center gap-0.5 px-1.5 py-[1px] rounded text-[9px] font-medium ${
        engine.cold_start_ms == null && !isAlwaysOn
          ? "bg-slate-100 text-slate-400 border border-slate-200"
          : "bg-slate-100 text-slate-600 border border-slate-200"
      }`}>
        <Timer size={8} className="opacity-60" />
        {formatColdStart(engine)}
      </span>
      {/* Re-measure link */}
      {showMeasure && !isAlwaysOn && (
        <button
          onClick={handleMeasure}
          disabled={measuring || measured}
          className={`inline-flex items-center gap-0.5 text-[9px] transition-colors disabled:opacity-40 ${
            measured ? "text-emerald-600" : "text-primary/70 hover:text-primary"
          }`}
          title="Re-measure cold start"
        >
          <RefreshCw size={8} className={measuring ? "animate-spin" : ""} />
          {measuring ? "measuring…" : measured ? "done" : "measure"}
        </button>
      )}
    </span>
  );
};

const SingleEngineView: React.FC<{
  duckdbEngines: EngineCatalogEntry[];
  databricksEngines: EngineCatalogEntry[];
  singleEngineId: string | null;
  onSelect: (id: string | null) => void;
  warehouseMappings: WarehouseMapping[];
}> = ({ duckdbEngines, databricksEngines, singleEngineId, onSelect, warehouseMappings }) => {
  if (duckdbEngines.length === 0 && databricksEngines.length === 0) {
    return (
      <div className="px-3 py-4 text-[12px] text-muted-foreground">
        No enabled engines available. Open <span className="font-medium text-primary">Manage Engines</span> to enable engines.
      </div>
    );
  }

  return (
    <div className="px-3 py-2 space-y-3">
      {/* DuckDB engines */}
      {duckdbEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <HardDrive size={13} strokeWidth={1.5} className="text-emerald-600" />
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">DuckDB</span>
          </div>
          <div className="space-y-0.5">
            {duckdbEngines.map(e => (
              <label
                key={e.id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                  singleEngineId === e.id ? "bg-primary/10" : "hover:bg-muted/50"
                }`}
              >
                <input
                  type="radio"
                  name="single-engine"
                  checked={singleEngineId === e.id}
                  onChange={() => onSelect(e.id)}
                  className="accent-primary"
                />
                <span className="flex flex-col">
                  <span className="flex items-center gap-1.5 text-[12px]">
                    <span className="inline-block w-[6px] h-[6px] rounded-full shrink-0 bg-status-success" />
                    <span className="font-medium text-foreground">{e.display_name}</span>
                  </span>
                  <span className="pl-[18px]"><EngineInfoBadges engine={e} showMeasure /></span>
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Databricks engines */}
      {databricksEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <Cloud size={13} strokeWidth={1.5} className="text-blue-600" />
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Databricks SQL</span>
          </div>
          <div className="space-y-0.5">
            {databricksEngines.map(e => {
              const warehouseName = getWarehouseName(e.id, warehouseMappings);
              const isMapped = warehouseName != null;
              return (
              <label
                key={e.id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded transition-colors ${
                  !isMapped ? "opacity-50 cursor-not-allowed" : singleEngineId === e.id ? "bg-primary/10 cursor-pointer" : "hover:bg-muted/50 cursor-pointer"
                }`}
              >
                <input
                  type="radio"
                  name="single-engine"
                  checked={singleEngineId === e.id}
                  onChange={() => isMapped && onSelect(e.id)}
                  disabled={!isMapped}
                  className="accent-primary"
                />
                <span className="flex flex-col">
                  <span className="flex items-center gap-1.5 text-[12px]">
                    <span className={`inline-block w-[6px] h-[6px] rounded-full shrink-0 ${
                      e.runtime_state === "running" ? "bg-status-success" : "bg-muted-foreground/40"
                    }`} />
                    <span className="font-medium text-foreground">{e.display_name}</span>
                    <span className="text-[10px] text-muted-foreground font-normal">
                      {isMapped ? `(${warehouseName})` : "(no mapping)"}
                    </span>
                  </span>
                  <span className="pl-[18px]"><EngineInfoBadges engine={e} showMeasure /></span>
                </span>
              </label>
              );
            })}
          </div>
        </div>
      )}

      <p className="mt-2 text-[11px] text-muted-foreground">
        All queries routed directly to the selected engine. No ML model used.
      </p>
    </div>
  );
};

// ---- Smart Routing View ----
const SmartRoutingView: React.FC<{
  models: Model[];
  activeModelId: number | null;
  onModelChange: (id: number) => void;
  modelEngines: EngineCatalogEntry[];
  enabledEngineIds: Set<string>;
  toggleEngineEnabled: (id: string) => void;
  warehouseMappings: WarehouseMapping[];
}> = ({ models, activeModelId, onModelChange, modelEngines, enabledEngineIds, toggleEngineEnabled, warehouseMappings }) => {
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [modelsDialogOpen, setModelsDialogOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    if (!modelDropdownOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [modelDropdownOpen]);

  const activeModel = models.find(m => m.id === activeModelId);

  if (models.length === 0) {
    return (
      <div className="px-3 py-4">
        <p className="text-[11px] text-muted-foreground mb-2">
          No trained models available. Create a model from benchmark data to enable smart routing.
        </p>
        <button
          onClick={() => setModelsDialogOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium text-primary border border-primary/30 rounded hover:bg-primary/10 transition-colors"
        >
          <Settings2 size={11} />
          Manage Models...
        </button>
        <ModelsDialog open={modelsDialogOpen} onClose={() => setModelsDialogOpen(false)} />
      </div>
    );
  }

  const duckdbModelEngines = modelEngines.filter(e => e.engine_type === "duckdb");
  const databricksModelEngines = modelEngines.filter(e => e.engine_type === "databricks_sql");

  return (
    <div className="px-3 py-2 space-y-3">
      {/* Model selector — custom dropdown with "Manage Models..." action */}
      <div>
        <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">
          <Brain size={11} className="inline mr-1" />
          Model
        </label>
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
            className="w-full flex items-center justify-between bg-card border border-border rounded px-2 py-1.5 text-[12px] font-medium text-foreground cursor-pointer hover:bg-muted/50 transition-colors shadow-sm"
          >
            <span className="truncate">
              {activeModel
                ? `Model #${activeModel.id} — R²=${activeModel.latency_model.r_squared} (${activeModel.linked_engines.length} engines)`
                : "Select a model..."
              }
            </span>
            <ChevronDown size={12} className={`shrink-0 ml-1 text-muted-foreground transition-transform ${modelDropdownOpen ? "rotate-180" : ""}`} />
          </button>

          {modelDropdownOpen && (
            <div className="absolute z-20 top-full left-0 right-0 mt-0.5 bg-popover border border-border rounded shadow-md overflow-hidden">
              {/* Model options */}
              {models.map(m => (
                <button
                  key={m.id}
                  onClick={() => { onModelChange(m.id); setModelDropdownOpen(false); }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 text-left text-[12px] transition-colors hover:bg-muted/50 ${
                    m.id === activeModelId ? "bg-primary/5" : ""
                  }`}
                >
                  <span className="font-medium text-foreground truncate">
                    Model #{m.id} — R²={m.latency_model.r_squared}
                  </span>
                  <span className="ml-auto text-[11px] text-muted-foreground shrink-0">
                    {m.linked_engines.length} engines
                  </span>
                  {m.id === activeModelId && (
                    <CheckCircle2 size={11} className="text-primary shrink-0" />
                  )}
                </button>
              ))}
              {/* Separator + Manage action */}
              <div className="border-t border-border">
                <button
                  onClick={() => { setModelDropdownOpen(false); setModelsDialogOpen(true); }}
                  className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left text-[12px] text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                >
                  <Settings2 size={11} />
                  Manage Models...
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Model's engines with checkboxes — grouped by type */}
      {activeModelId && modelEngines.length > 0 && (
        <div className="space-y-3">
          {/* DuckDB engines */}
          {duckdbModelEngines.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <HardDrive size={13} strokeWidth={1.5} className="text-emerald-600" />
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">DuckDB</span>
                <span className="text-[11px] text-muted-foreground">
                  ({duckdbModelEngines.filter(e => enabledEngineIds.has(e.id)).length}/{duckdbModelEngines.length})
                </span>
              </div>
              <div className="space-y-0.5">
                {duckdbModelEngines.map(e => {
                  const isEnabled = enabledEngineIds.has(e.id);
                  return (
                    <label
                      key={e.id}
                      className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors hover:bg-muted/50 ${
                        isEnabled ? "bg-primary/5" : ""
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isEnabled}
                        onChange={() => toggleEngineEnabled(e.id)}
                        className="accent-primary"
                      />
                      <span className="flex flex-col">
                        <span className="flex items-center gap-1.5 text-[12px]">
                          <span className={`inline-block w-[5px] h-[5px] rounded-full shrink-0 ${
                            e.runtime_state === "running" ? "bg-status-success" : "bg-muted-foreground/40"
                          }`} />
                          <span className="font-medium text-foreground">{e.display_name}</span>
                        </span>
                        <span className="pl-[17px]"><EngineInfoBadges engine={e} showMeasure /></span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {/* Databricks engines */}
          {databricksModelEngines.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Cloud size={13} strokeWidth={1.5} className="text-blue-600" />
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Databricks SQL</span>
                <span className="text-[11px] text-muted-foreground">
                  ({databricksModelEngines.filter(e => enabledEngineIds.has(e.id)).length}/{databricksModelEngines.length})
                </span>
              </div>
              <div className="space-y-0.5">
                {databricksModelEngines.map(e => {
                  const isEnabled = enabledEngineIds.has(e.id);
                  const warehouseName = getWarehouseName(e.id, warehouseMappings);
                  const isMapped = warehouseName != null;
                  return (
                    <label
                      key={e.id}
                      className={`flex items-center gap-2 px-2 py-1.5 rounded transition-colors ${
                        !isMapped ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-muted/50"
                      } ${isEnabled && isMapped ? "bg-primary/5" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={isEnabled}
                        onChange={() => isMapped && toggleEngineEnabled(e.id)}
                        disabled={!isMapped}
                        className="accent-primary"
                      />
                      <span className="flex flex-col">
                        <span className="flex items-center gap-1.5 text-[12px]">
                          <span className={`inline-block w-[5px] h-[5px] rounded-full shrink-0 ${
                            e.runtime_state === "running" ? "bg-status-success" : "bg-muted-foreground/40"
                          }`} />
                          <span className="font-medium text-foreground">{e.display_name}</span>
                          <span className="text-[10px] text-muted-foreground font-normal">
                            {isMapped ? `(${warehouseName})` : "(no mapping)"}
                          </span>
                        </span>
                        <span className="pl-[17px]"><EngineInfoBadges engine={e} showMeasure /></span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          <p className="text-[11px] text-muted-foreground">
            Only engines supported by the selected model are shown. Uncheck to exclude from routing.
          </p>
        </div>
      )}

      {/* UX #26: Help text when no model is active but models exist */}
      {!activeModelId && models.length > 0 && (
        <div className="px-3 py-3 text-[11px] text-muted-foreground">
          <Brain size={14} className="mx-auto mb-1.5 text-muted-foreground/40" />
          <p className="text-center">
            Select a model above to configure engine routing.
          </p>
        </div>
      )}

      <ModelsDialog open={modelsDialogOpen} onClose={() => setModelsDialogOpen(false)} />
    </div>
  );
};

// ---- Benchmarking View ----
// Multi-select all engines (no model, no profile). Used to run benchmarks.
const BenchmarkingView: React.FC<{
  duckdbEngines: EngineCatalogEntry[];
  databricksEngines: EngineCatalogEntry[];
  benchmarkEngineIds: Set<string>;
  toggleBenchmarkEngine: (id: string) => void;
}> = ({ duckdbEngines, databricksEngines, benchmarkEngineIds, toggleBenchmarkEngine }) => {
  const allEngines = [...duckdbEngines, ...databricksEngines];
  const selectedCount = benchmarkEngineIds.size;

  if (allEngines.length === 0) {
    return (
      <div className="px-3 py-4 text-[12px] text-muted-foreground">
        No engines available. Start a DuckDB engine or connect a workspace.
      </div>
    );
  }

  return (
    <div className="px-3 py-2 space-y-3">
      {/* Header with count */}
      <div className="flex items-center gap-1.5">
        <FlaskConical size={11} className="text-amber-600" />
        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          Select engines to benchmark
        </span>
        {selectedCount > 0 && (
          <span className="ml-auto text-[11px] text-amber-700 font-medium">
            {selectedCount} selected
          </span>
        )}
      </div>

      {/* DuckDB engines */}
      {duckdbEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <HardDrive size={13} strokeWidth={1.5} className="text-emerald-600" />
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">DuckDB</span>
            <span className="text-[11px] text-muted-foreground">
              ({duckdbEngines.filter(e => benchmarkEngineIds.has(e.id)).length}/{duckdbEngines.length})
            </span>
          </div>
          <div className="space-y-0.5">
            {duckdbEngines.map(e => {
              const isChecked = benchmarkEngineIds.has(e.id);
              return (
                <label
                  key={e.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors hover:bg-muted/50 ${
                    isChecked ? "bg-amber-50" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleBenchmarkEngine(e.id)}
                    className="accent-amber-600"
                  />
                  <span className="flex flex-col">
                    <span className="flex items-center gap-1.5 text-[12px]">
                      <span className="inline-block w-[5px] h-[5px] rounded-full shrink-0 bg-status-success" />
                      <span className="font-medium text-foreground">{e.display_name}</span>
                    </span>
                    <span className="pl-[17px]"><EngineInfoBadges engine={e} showMeasure /></span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Databricks engines */}
      {databricksEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <Cloud size={13} strokeWidth={1.5} className="text-blue-600" />
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Databricks SQL</span>
            <span className="text-[11px] text-muted-foreground">
              ({databricksEngines.filter(e => benchmarkEngineIds.has(e.id)).length}/{databricksEngines.length})
            </span>
          </div>
          <div className="space-y-0.5">
            {databricksEngines.map(e => {
              const isChecked = benchmarkEngineIds.has(e.id);
              return (
                <label
                  key={e.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors hover:bg-muted/50 ${
                    isChecked ? "bg-amber-50" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleBenchmarkEngine(e.id)}
                    className="accent-amber-600"
                  />
                      <span className="flex flex-col">
                        <span className="flex items-center gap-1.5 text-[12px]">
                          <span className={`inline-block w-[5px] h-[5px] rounded-full shrink-0 ${
                            e.runtime_state === "running" ? "bg-status-success" : "bg-muted-foreground/40"
                          }`} />
                          <span className="font-medium text-foreground">{e.display_name}</span>

                        </span>
                        <span className="pl-[17px]"><EngineInfoBadges engine={e} showMeasure /></span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

      <p className="text-[11px] text-muted-foreground">
        Select engines to include in the benchmark run. Each engine will be tested sequentially.
        {selectedCount === 0 && (
          <span className="block mt-1 text-amber-600 font-medium">
            Select at least one engine, then use "Run Benchmark" in the Collections panel.
          </span>
        )}
      </p>
    </div>
  );
};
