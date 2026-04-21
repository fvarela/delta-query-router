import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { Server, AlertTriangle, Brain, ChevronDown, Cloud, HardDrive, Unlink, CheckCircle2, FlaskConical, Settings2, RefreshCw } from "lucide-react";
import type { EngineCatalogEntry, Model, DiscoveredWarehouse, WarehouseMapping } from "@/types";
import { ModelsDialog } from "./ModelsDialog";

export const EnginesTable: React.FC = () => {
  const {
    engines, connectedWorkspace,
    routingMode, setRoutingMode,
    singleEngineId, setSingleEngineId,
    activeModelId, setActiveModelId, models,
    enabledEngineIds, toggleEngineEnabled, setAllEnginesEnabled,
    benchmarkEngineIds, toggleBenchmarkEngine,
    profileWorkspaceBinding,
    discoveredWarehouses, reloadDiscoveredWarehouses,
    warehouseMappings, setWarehouseMapping,
    unlinkProfileWorkspace,
  } = useApp();

  // All engines grouped by type for single-engine mode
  // DuckDB: only show running engines. Databricks: show all (workspace status shown inline).
  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb" && e.runtime_state === "running");
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql");

  // Refresh warehouse states
  const [refreshing, setRefreshing] = useState(false);
  const handleRefreshWarehouses = async () => {
    setRefreshing(true);
    await reloadDiscoveredWarehouses();
    setTimeout(() => setRefreshing(false), 600); // keep spin animation visible briefly
  };

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

  // Workspace dependency satisfied? If profile binds to a workspace, check it matches the connected one.
  // When not satisfied, Databricks engines should be fully locked (no warehouse selection).
  const workspaceSatisfied = !profileWorkspaceBinding ||
    (connectedWorkspace !== null && connectedWorkspace.url === profileWorkspaceBinding.workspaceUrl);

  return (
    <div className="text-[12px]">
      <div className="px-3 py-2 border-b border-panel-border flex items-center gap-2 shadow-section">
        <Server size={13} className="text-primary shrink-0" />
        <span className="font-semibold text-foreground">Routing Settings</span>
      </div>

      {/* Workspace dependency warning — shown when profile requires a workspace that isn't connected (not in benchmark mode) */}
      {profileWorkspaceBinding && routingMode !== "benchmark" && (
        <WorkspaceDependencyBanner
          binding={profileWorkspaceBinding}
          connectedWorkspace={connectedWorkspace}
          onUnlink={unlinkProfileWorkspace}
        />
      )}

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
          hasConnectedWorkspace={connectedWorkspace !== null}
          workspaceSatisfied={workspaceSatisfied}
          discoveredWarehouses={discoveredWarehouses}
          warehouseMappings={warehouseMappings}
          setWarehouseMapping={setWarehouseMapping}
          onRefreshWarehouses={handleRefreshWarehouses}
          refreshing={refreshing}
        />
      ) : routingMode === "smart" ? (
        <SmartRoutingView
          models={models}
          activeModelId={activeModelId}
          onModelChange={handleModelChange}
          modelEngines={modelEngines}
          enabledEngineIds={enabledEngineIds}
          toggleEngineEnabled={toggleEngineEnabled}
          engines={engines}
          hasConnectedWorkspace={connectedWorkspace !== null}
          workspaceSatisfied={workspaceSatisfied}
          discoveredWarehouses={discoveredWarehouses}
          warehouseMappings={warehouseMappings}
          setWarehouseMapping={setWarehouseMapping}
          onRefreshWarehouses={handleRefreshWarehouses}
          refreshing={refreshing}
        />
      ) : (
        <BenchmarkingView
          duckdbEngines={duckdbEngines}
          databricksEngines={databricksEngines}
          benchmarkEngineIds={benchmarkEngineIds}
          toggleBenchmarkEngine={toggleBenchmarkEngine}
          hasConnectedWorkspace={connectedWorkspace !== null}
          workspaceSatisfied={workspaceSatisfied}
          discoveredWarehouses={discoveredWarehouses}
          warehouseMappings={warehouseMappings}
          setWarehouseMapping={setWarehouseMapping}
          onRefreshWarehouses={handleRefreshWarehouses}
          refreshing={refreshing}
        />
      )}
    </div>
  );
};

// ---- Databricks Section Header with refresh button ----
const DatabricksHeader: React.FC<{
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}> = ({ onRefresh, refreshing }) => (
  <div className="flex items-center gap-1.5 mb-1.5">
    <Cloud size={13} strokeWidth={1.5} className="text-blue-600" />
    <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Databricks SQL</span>
    <button
      onClick={onRefresh}
      className="ml-auto p-0.5 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
      title="Refresh warehouse states"
    >
      <RefreshCw size={11} strokeWidth={1.5} className={refreshing ? "animate-spin" : ""} />
    </button>
  </div>
);

// ---- Workspace Dependency Banner ----
// Shown when a profile has a workspace dependency (via warehouse mappings)
const WorkspaceDependencyBanner: React.FC<{
  binding: { workspaceId: string; workspaceName: string; workspaceUrl: string };
  connectedWorkspace: { id: string; name: string; url: string } | null;
  onUnlink: () => void;
}> = ({ binding, connectedWorkspace, onUnlink }) => {
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const isSatisfied = connectedWorkspace !== null && connectedWorkspace.url === binding.workspaceUrl;
  const isWrongWorkspace = connectedWorkspace !== null && connectedWorkspace.url !== binding.workspaceUrl;

  const handleUnlink = () => {
    onUnlink();
    setConfirmUnlink(false);
  };

  if (isSatisfied) {
    // Dependency satisfied — show green confirmation with option to remove
    return (
      <div className="px-3 py-1.5 border-b border-panel-border bg-emerald-50">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 size={11} className="text-emerald-600 shrink-0" />
          <span className="text-[11px] text-emerald-700 font-medium truncate">{binding.workspaceName}</span>
          <span className="text-[10px] text-emerald-600">connected</span>
          <button
            onClick={() => setConfirmUnlink(!confirmUnlink)}
            className="ml-auto text-[10px] text-emerald-600 hover:text-emerald-800 transition-colors"
            title="Remove workspace dependency"
          >
            <Unlink size={10} />
          </button>
        </div>
        {confirmUnlink && (
          <div className="mt-1.5 p-1.5 rounded bg-amber-50 border border-amber-200">
            <p className="text-[11px] text-amber-800 mb-1.5">
              This will remove the workspace dependency and clear all warehouse mappings for Databricks engines.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={handleUnlink}
                className="flex items-center gap-1 text-[11px] text-amber-700 hover:text-amber-900 font-medium transition-colors"
              >
                <Unlink size={10} />
                Confirm unlink
              </button>
              <button
                onClick={() => setConfirmUnlink(false)}
                className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Dependency NOT satisfied — show warning
  return (
    <div className="px-3 py-2 border-b border-panel-border bg-amber-50">
      <div className="flex items-center gap-1.5 mb-1">
        <AlertTriangle size={11} className="text-amber-600 shrink-0" />
        <span className="text-[11px] text-amber-800 font-medium">Workspace required</span>
      </div>
      <div className="text-[11px] text-amber-700 mb-1.5">
        {isWrongWorkspace ? (
          <>Profile needs <span className="font-medium">{binding.workspaceName}</span>, but you're connected to <span className="font-medium">{connectedWorkspace!.name}</span>.</>
        ) : (
          <>Profile needs <span className="font-medium">{binding.workspaceName}</span>. Connect via the left panel.</>
        )}
      </div>
      <button
        onClick={onUnlink}
        className="flex items-center gap-1 text-[11px] text-amber-700 hover:text-amber-900 transition-colors font-medium"
      >
        <Unlink size={10} />
        Unlink workspace &amp; clear mappings
      </button>
    </div>
  );
};

// ---- Single Engine View ----
const SingleEngineView: React.FC<{
  duckdbEngines: EngineCatalogEntry[];
  databricksEngines: EngineCatalogEntry[];
  singleEngineId: string | null;
  onSelect: (id: string | null) => void;
  hasConnectedWorkspace: boolean;
  workspaceSatisfied: boolean;
  discoveredWarehouses: DiscoveredWarehouse[];
  warehouseMappings: WarehouseMapping[];
  setWarehouseMapping: (engineId: string, warehouseId: string | null, warehouseName: string | null) => void;
  onRefreshWarehouses: () => Promise<void>;
  refreshing: boolean;
}> = ({ duckdbEngines, databricksEngines, singleEngineId, onSelect, hasConnectedWorkspace, workspaceSatisfied, discoveredWarehouses, warehouseMappings, setWarehouseMapping, onRefreshWarehouses, refreshing }) => {
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
                <span className="flex items-center gap-1.5 text-[12px]">
                  <span className="inline-block w-[6px] h-[6px] rounded-full shrink-0 bg-status-success" />
                  <span className="font-medium text-foreground">{e.display_name}</span>
                </span>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {e.config.memory_gb}GB / {e.config.cpu_count}CPU
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Databricks engines */}
      {databricksEngines.length > 0 && (
        <div>
          <DatabricksHeader onRefresh={onRefreshWarehouses} refreshing={refreshing} />
          <div className="space-y-1">
            {databricksEngines.map(e => {
              const matchingWarehouses = discoveredWarehouses.filter(w => w.matchingEngineId === e.id);
              const currentMapping = warehouseMappings.find(m => m.engineId === e.id);
              const isSelected = singleEngineId === e.id;

              return (
                <DatabricksEngineRow
                  key={e.id}
                  engine={e}
                  isSelected={isSelected}
                  onSelect={() => onSelect(e.id)}
                  hasWorkspace={hasConnectedWorkspace}
                  workspaceSatisfied={workspaceSatisfied}
                  matchingWarehouses={matchingWarehouses}
                  currentMapping={currentMapping ?? null}
                  setWarehouseMapping={setWarehouseMapping}
                  selectionMode="radio"
                />
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

// ---- Databricks Engine Row (shared between single & smart mode) ----
const DatabricksEngineRow: React.FC<{
  engine: EngineCatalogEntry;
  isSelected: boolean;
  onSelect: () => void;
  hasWorkspace: boolean;
  workspaceSatisfied: boolean;
  matchingWarehouses: DiscoveredWarehouse[];
  currentMapping: WarehouseMapping | null;
  setWarehouseMapping: (engineId: string, warehouseId: string | null, warehouseName: string | null) => void;
  selectionMode: "radio" | "checkbox";
  isEnabled?: boolean;
  onToggle?: () => void;
  accentColor?: "primary" | "amber";
  isBenchmarkMode?: boolean;
}> = ({ engine, isSelected, onSelect, hasWorkspace, workspaceSatisfied, matchingWarehouses, currentMapping, setWarehouseMapping, selectionMode, isEnabled, onToggle, accentColor = "primary", isBenchmarkMode = false }) => {
  const [warehouseDropdownOpen, setWarehouseDropdownOpen] = useState(false);

  if (!hasWorkspace) {
    // No workspace connected — show warning with unchecked disabled checkbox (UX #31)
    return (
      <div className="flex items-center gap-2 px-2 py-1.5 rounded opacity-60">
        {selectionMode === "radio" ? (
          <input type="radio" name="single-engine" disabled className="accent-primary" />
        ) : (
          <input type="checkbox" checked={false} disabled className="accent-primary" />
        )}
        <span className="flex items-center gap-1.5 text-[12px]">
          <AlertTriangle size={11} className="text-amber-500 shrink-0" />
          <span className="font-medium text-muted-foreground">{engine.display_name}</span>
        </span>
        <span className="ml-auto text-[11px] text-amber-600 italic">No workspace</span>
      </div>
    );
  }

  if (!workspaceSatisfied) {
    // Workspace connected but it's the WRONG one — fully disabled, no warehouse interaction
    return (
      <div className="rounded opacity-50 cursor-not-allowed">
        <div className="flex items-center gap-2 px-2 py-1.5">
          {selectionMode === "radio" ? (
            <input type="radio" name="single-engine" disabled className="accent-primary" />
          ) : (
            <input type="checkbox" checked={isEnabled ?? false} disabled className="accent-primary" />
          )}
          <span className="flex items-center gap-1.5 text-[12px]">
            <AlertTriangle size={11} className="text-amber-500 shrink-0" />
            <span className="font-medium text-muted-foreground">{engine.display_name}</span>
          </span>
          <span className="ml-auto text-[11px] text-muted-foreground shrink-0">
            {engine.config.cluster_size}
          </span>
        </div>
        <div className="px-2 pb-1.5 pl-[30px]">
          <span className="text-[11px] text-amber-600 italic">Wrong workspace connected</span>
        </div>
      </div>
    );
  }

  // Has correct workspace — show warehouse info
  const mappedWarehouse = currentMapping?.warehouseId
    ? matchingWarehouses.find(w => w.id === currentMapping.warehouseId) ?? null
    : null;
  const warehouseCount = matchingWarehouses.length;
  const isMapped = mappedWarehouse !== null;
  // In benchmark mode, ephemeral warehouses are created on the fly — no mapping required
  const isInteractive = isMapped || isBenchmarkMode;

  return (
    <div className={`rounded border transition-colors ${
      isSelected ? "border-primary/30 bg-primary/5" : accentColor === "amber" && isEnabled ? "border-amber-300/30 bg-amber-50" : "border-transparent"
    }`}>
      <div className={`flex items-center gap-2 px-2 py-1.5 ${!isInteractive ? "opacity-60" : ""}`}>
        {selectionMode === "radio" ? (
          <input
            type="radio"
            name="single-engine"
            checked={isSelected}
            onChange={onSelect}
            disabled={!isMapped}
            className="accent-primary"
            title={!isMapped ? "Map a warehouse first" : undefined}
          />
        ) : (
          <input
            type="checkbox"
            checked={isEnabled ?? false}
            onChange={onToggle}
            disabled={!isInteractive}
            className={accentColor === "amber" ? "accent-amber-600" : "accent-primary"}
            title={!isInteractive ? "Map a warehouse first to enable this engine" : undefined}
          />
        )}
        <span className="flex items-center gap-1.5 text-[12px] flex-1 min-w-0">
          <span className="font-medium text-foreground">{engine.display_name}</span>
        </span>
        <span className="text-[11px] text-muted-foreground shrink-0">
          {engine.config.cluster_size}
        </span>
      </div>

      {/* Warehouse mapping row */}
      <div className="px-2 pb-1.5 pl-[30px]">
        {warehouseCount === 0 ? (
          <span className="text-[11px] text-muted-foreground/60 italic">
            {isBenchmarkMode ? "Ephemeral warehouse — created automatically" : "No matching warehouses found"}
          </span>
        ) : mappedWarehouse ? (
          <div className="flex items-center gap-1.5">
            <span className={`inline-block w-[4px] h-[4px] rounded-full shrink-0 ${
              mappedWarehouse.state === "RUNNING" ? "bg-emerald-500" : "bg-muted-foreground/30"
            }`} />
            <span className="text-[11px] text-foreground font-medium">{mappedWarehouse.name}</span>
            <span className="text-[10px] text-muted-foreground">({mappedWarehouse.state.toLowerCase()})</span>
            <button
              onClick={() => setWarehouseDropdownOpen(!warehouseDropdownOpen)}
              className="ml-auto text-[10px] text-primary hover:text-primary/80 transition-colors"
            >
              Change
            </button>
          </div>
        ) : (
          <button
            onClick={() => setWarehouseDropdownOpen(!warehouseDropdownOpen)}
            className="text-[11px] text-primary hover:text-primary/80 transition-colors"
          >
            {warehouseCount} warehouse{warehouseCount !== 1 ? "s" : ""} available — select one
          </button>
        )}

        {/* Warehouse dropdown */}
        {warehouseDropdownOpen && warehouseCount > 0 && (
          <div className="mt-1 border border-border rounded bg-popover shadow-md overflow-hidden">
            {matchingWarehouses.map(wh => (
              <button
                key={wh.id}
                onClick={() => {
                  setWarehouseMapping(engine.id, wh.id, wh.name);
                  setWarehouseDropdownOpen(false);
                }}
                className={`w-full flex items-center gap-2 px-2 py-1.5 text-left text-[11px] hover:bg-muted/50 transition-colors ${
                  currentMapping?.warehouseId === wh.id ? "bg-primary/5" : ""
                }`}
              >
                <span className={`inline-block w-[4px] h-[4px] rounded-full shrink-0 ${
                  wh.state === "RUNNING" ? "bg-emerald-500" : "bg-muted-foreground/30"
                }`} />
                <span className="font-medium text-foreground">{wh.name}</span>
                <span className="text-muted-foreground">({wh.state.toLowerCase()})</span>
                {currentMapping?.warehouseId === wh.id && (
                  <span className="ml-auto text-primary font-medium">current</span>
                )}
              </button>
            ))}
            <button
              onClick={() => {
                setWarehouseMapping(engine.id, null, null);
                setWarehouseDropdownOpen(false);
              }}
              className="w-full px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted/50 transition-colors border-t border-border"
            >
              Clear mapping
            </button>
          </div>
        )}
      </div>
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
  engines: EngineCatalogEntry[];
  hasConnectedWorkspace: boolean;
  workspaceSatisfied: boolean;
  discoveredWarehouses: DiscoveredWarehouse[];
  warehouseMappings: WarehouseMapping[];
  setWarehouseMapping: (engineId: string, warehouseId: string | null, warehouseName: string | null) => void;
  onRefreshWarehouses: () => Promise<void>;
  refreshing: boolean;
}> = ({ models, activeModelId, onModelChange, modelEngines, enabledEngineIds, toggleEngineEnabled, engines, hasConnectedWorkspace, workspaceSatisfied, discoveredWarehouses, warehouseMappings, setWarehouseMapping, onRefreshWarehouses, refreshing }) => {
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
                      <span className="flex items-center gap-1.5 text-[12px]">
                        <span className={`inline-block w-[5px] h-[5px] rounded-full shrink-0 ${
                          e.runtime_state === "running" ? "bg-status-success" : "bg-muted-foreground/40"
                        }`} />
                        <span className="font-medium text-foreground">{e.display_name}</span>
                      </span>
                      <span className="ml-auto text-[11px] text-muted-foreground">
                        {e.config.memory_gb}GB / {e.config.cpu_count}CPU
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
                <button
                  onClick={onRefreshWarehouses}
                  className="ml-auto p-0.5 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                  title="Refresh warehouse states"
                >
                  <RefreshCw size={11} strokeWidth={1.5} className={refreshing ? "animate-spin" : ""} />
                </button>
              </div>
              <div className="space-y-1">
                {databricksModelEngines.map(e => {
                  const matchingWarehouses = discoveredWarehouses.filter(w => w.matchingEngineId === e.id);
                  const currentMapping = warehouseMappings.find(m => m.engineId === e.id);
                  const isEnabled = enabledEngineIds.has(e.id);

                  return (
                    <DatabricksEngineRow
                      key={e.id}
                      engine={e}
                      isSelected={false}
                      onSelect={() => {}}
                      hasWorkspace={hasConnectedWorkspace}
                      workspaceSatisfied={workspaceSatisfied}
                      matchingWarehouses={matchingWarehouses}
                      currentMapping={currentMapping ?? null}
                      setWarehouseMapping={setWarehouseMapping}
                      selectionMode="checkbox"
                      isEnabled={isEnabled}
                      onToggle={() => toggleEngineEnabled(e.id)}
                    />
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
  hasConnectedWorkspace: boolean;
  workspaceSatisfied: boolean;
  discoveredWarehouses: DiscoveredWarehouse[];
  warehouseMappings: WarehouseMapping[];
  setWarehouseMapping: (engineId: string, warehouseId: string | null, warehouseName: string | null) => void;
  onRefreshWarehouses: () => Promise<void>;
  refreshing: boolean;
}> = ({ duckdbEngines, databricksEngines, benchmarkEngineIds, toggleBenchmarkEngine, hasConnectedWorkspace, workspaceSatisfied, discoveredWarehouses, warehouseMappings, setWarehouseMapping, onRefreshWarehouses, refreshing }) => {
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
                  <span className="flex items-center gap-1.5 text-[12px]">
                    <span className="inline-block w-[5px] h-[5px] rounded-full shrink-0 bg-status-success" />
                    <span className="font-medium text-foreground">{e.display_name}</span>
                  </span>
                  <span className="ml-auto text-[11px] text-muted-foreground">
                    {e.config.memory_gb}GB / {e.config.cpu_count}CPU
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
            <button
              onClick={onRefreshWarehouses}
              className="ml-auto p-0.5 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
              title="Refresh warehouse states"
            >
              <RefreshCw size={11} strokeWidth={1.5} className={refreshing ? "animate-spin" : ""} />
            </button>
          </div>
          <div className="space-y-1">
            {databricksEngines.map(e => {
              const matchingWarehouses = discoveredWarehouses.filter(w => w.matchingEngineId === e.id);
              const currentMapping = warehouseMappings.find(m => m.engineId === e.id);
              const isChecked = benchmarkEngineIds.has(e.id);

              return (
                <DatabricksEngineRow
                  key={e.id}
                  engine={e}
                  isSelected={false}
                  onSelect={() => {}}
                  hasWorkspace={hasConnectedWorkspace}
                  workspaceSatisfied={workspaceSatisfied}
                  matchingWarehouses={matchingWarehouses}
                  currentMapping={currentMapping ?? null}
                  setWarehouseMapping={setWarehouseMapping}
                  selectionMode="checkbox"
                  isEnabled={isChecked}
                  onToggle={() => toggleBenchmarkEngine(e.id)}
                  accentColor="amber"
                  isBenchmarkMode={true}
                />
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
