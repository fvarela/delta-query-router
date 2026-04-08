import React from "react";
import { useApp } from "@/contexts/AppContext";
import { X, Lock, HardDrive, Cloud, Power, PowerOff } from "lucide-react";
import type { EngineCatalogEntry } from "@/types";

export const EngineCatalogDialog: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { engines, toggleCatalogEngine, engineProfileCounts } = useApp();

  if (!open) return null;

  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb");
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql");

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
            toggleCatalogEngine={toggleCatalogEngine}
            profileCounts={engineProfileCounts}
            showScalePolicy
          />

          {/* Databricks Section */}
          <EngineSection
            title="Databricks SQL"
            subtitle="Declarations of supported warehouse types"
            icon={<Cloud size={12} className="text-blue-600" />}
            engines={databricksEngines}
            toggleCatalogEngine={toggleCatalogEngine}
            profileCounts={engineProfileCounts}
            showScalePolicy={false}
          />
        </div>

        {/* Footer */}
        <div className="px-4 py-2.5 border-t border-border bg-muted/30">
          <p className="text-[10px] text-muted-foreground">
            Engines in use by routing profiles are locked from disabling.
            Scale policy changes are blocked for DuckDB engines referenced by active profiles.
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
  toggleCatalogEngine: (id: string, field: "enabled" | "scale_policy", value: any) => void;
  profileCounts: Record<string, number>;
  showScalePolicy: boolean;
}> = ({ title, subtitle, icon, engines, toggleCatalogEngine, profileCounts, showScalePolicy }) => {
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
          const usageCount = profileCounts[engine.id] ?? 0;
          const isLocked = usageCount > 0;

          return (
            <EngineRow
              key={engine.id}
              engine={engine}
              isLocked={isLocked}
              usageCount={usageCount}
              showScalePolicy={showScalePolicy}
              toggleCatalogEngine={toggleCatalogEngine}
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
  showScalePolicy: boolean;
  toggleCatalogEngine: (id: string, field: "enabled" | "scale_policy", value: any) => void;
}> = ({ engine, isLocked, usageCount, showScalePolicy, toggleCatalogEngine }) => {
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
            if (!isLocked) toggleCatalogEngine(engine.id, "enabled", !engine.enabled);
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

      {/* Scale policy toggle (DuckDB only) */}
      {showScalePolicy && (
        <div className="shrink-0">
          <ScalePolicyToggle
            value={engine.scale_policy}
            locked={isLocked}
            onChange={(policy) => toggleCatalogEngine(engine.id, "scale_policy", policy)}
          />
        </div>
      )}
    </div>
  );
};

// ---- Scale Policy Toggle ----
const ScalePolicyToggle: React.FC<{
  value: "always_on" | "scale_to_zero";
  locked: boolean;
  onChange: (v: "always_on" | "scale_to_zero") => void;
}> = ({ value, locked, onChange }) => {
  const isAlwaysOn = value === "always_on";

  return (
    <button
      onClick={() => {
        if (!locked) onChange(isAlwaysOn ? "scale_to_zero" : "always_on");
      }}
      disabled={locked}
      className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border transition-colors ${
        locked
          ? "border-border text-muted-foreground/50 cursor-not-allowed bg-muted/20"
          : isAlwaysOn
            ? "border-emerald-200 text-emerald-700 bg-emerald-50 hover:bg-emerald-100"
            : "border-border text-muted-foreground bg-card hover:bg-muted/50"
      }`}
      title={
        locked
          ? "Cannot change while in use by profiles"
          : isAlwaysOn
            ? "Running 24/7 — click to enable scale-to-zero"
            : "Scales to zero when idle — click for always-on"
      }
    >
      {isAlwaysOn ? (
        <>
          <Power size={9} />
          Always On
        </>
      ) : (
        <>
          <PowerOff size={9} />
          Scale to Zero
        </>
      )}
    </button>
  );
};
