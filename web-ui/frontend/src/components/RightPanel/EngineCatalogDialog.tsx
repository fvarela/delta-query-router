import React from "react";
import { useApp } from "@/contexts/AppContext";
import { X, Lock, HardDrive, Cloud } from "lucide-react";
import type { EngineCatalogEntry } from "@/types";

export const EngineCatalogDialog: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { engines, toggleEngineEnabled } = useApp();

  if (!open) return null;

  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb");
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql");

  // Wrapper: toggleEngineEnabled takes just an id
  const handleToggle = (id: string) => toggleEngineEnabled(id);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* Dialog */}
      <div className="relative bg-card border border-border rounded-lg shadow-xl w-[480px] max-h-[80vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div>
            <h2 className="text-[13px] font-semibold text-foreground">Engine Catalog</h2>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              Predefined engine types available for benchmarking and routing
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground"
          >
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* DuckDB Section */}
          <EngineSection
            title="DuckDB"
            subtitle="System-managed, runs as K8s pods"
            icon={<HardDrive size={12} className="text-emerald-600" />}
            engines={duckdbEngines}
            onToggle={handleToggle}
          />

          {/* Databricks Section */}
          <EngineSection
            title="Databricks SQL"
            subtitle="Declarations of supported warehouse types"
            icon={<Cloud size={12} className="text-blue-600" />}
            engines={databricksEngines}
            onToggle={handleToggle}
          />
        </div>

        {/* Footer */}
        <div className="px-4 py-2.5 border-t border-border bg-muted/30">
          <p className="text-[10px] text-muted-foreground">
            Toggling a DuckDB engine on/off scales its K8s Deployment automatically.
            Engines in use by routing profiles are locked from disabling.
          </p>
        </div>
      </div>
    </div>
  );
};

// ---- Engine Section ----
const EngineSection: React.FC<{
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  engines: EngineCatalogEntry[];
  onToggle: (id: string) => void;
}> = ({ title, subtitle, icon, engines, onToggle }) => {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <div>
          <span className="text-[11px] font-semibold text-foreground">{title}</span>
          <span className="text-[10px] text-muted-foreground ml-2">{subtitle}</span>
        </div>
      </div>

      <div className="space-y-1">
        {engines.map(engine => {
          const usageCount = engine.profile_usage_count ?? 0;
          const isLocked = usageCount > 0;

          return (
            <EngineRow
              key={engine.id}
              engine={engine}
              isLocked={isLocked}
              usageCount={usageCount}
              onToggle={onToggle}
            />
          );
        })}
      </div>
    </div>
  );
};

// ---- Individual Engine Row ----
const EngineRow: React.FC<{
  engine: EngineCatalogEntry;
  isLocked: boolean;
  usageCount: number;
  onToggle: (id: string) => void;
}> = ({ engine, isLocked, usageCount, onToggle }) => {
  const configLabel = engine.engine_type === "duckdb"
    ? `${engine.config.memory_gb}GB / ${engine.config.cpu_count} CPU`
    : engine.config.cluster_size;

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-md border transition-colors ${
      engine.enabled
        ? "border-border bg-card"
        : "border-transparent bg-muted/30"
    }`}>
      {/* Enable/disable toggle */}
      <label className={`shrink-0 ${isLocked ? "cursor-not-allowed" : "cursor-pointer"}`}>
        <input
          type="checkbox"
          checked={engine.enabled}
          onChange={() => {
            if (!isLocked) onToggle(engine.id);
          }}
          disabled={isLocked && engine.enabled}
          className="accent-primary"
          title={isLocked && engine.enabled ? `In use by ${usageCount} profile(s) — cannot disable` : undefined}
        />
      </label>

      {/* Engine info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={`text-[11px] font-medium ${engine.enabled ? "text-foreground" : "text-muted-foreground"}`}>
            {engine.display_name}
          </span>
          {isLocked && (
            <Lock size={9} className="text-amber-500 shrink-0" title={`Used by ${usageCount} profile(s)`} />
          )}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-muted-foreground">{configLabel}</span>
          <span className="text-[10px] text-muted-foreground/50">|</span>
          <span className="text-[10px] text-muted-foreground">Cost tier {engine.cost_tier}</span>
          {usageCount > 0 && (
            <>
              <span className="text-[10px] text-muted-foreground/50">|</span>
              <span className="text-[10px] text-amber-600">
                {usageCount} profile{usageCount !== 1 ? "s" : ""}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Runtime state badge */}
      <div className="shrink-0">
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
          engine.runtime_state === "running"
            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
            : engine.runtime_state === "stopped"
              ? "bg-muted text-muted-foreground border border-border"
              : "bg-amber-50 text-amber-700 border border-amber-200"
        }`}>
          {engine.runtime_state}
        </span>
      </div>
    </div>
  );
};
