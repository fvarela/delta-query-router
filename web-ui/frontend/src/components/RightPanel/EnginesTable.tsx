import React from "react";
import { useApp } from "@/contexts/AppContext";
import { Server } from "lucide-react";
import type { EngineRuntimeState } from "@/types";

const runtimeStateStyle = (state: EngineRuntimeState) => {
  switch (state) {
    case "running": return "bg-status-success";
    case "starting": return "bg-status-warning";
    case "stopped":
    case "unknown":
    default: return "bg-muted-foreground/40";
  }
};

const runtimeStateLabel = (state: EngineRuntimeState) => {
  switch (state) {
    case "running": return "Running";
    case "starting": return "Starting";
    case "stopped": return "Stopped";
    case "unknown": return "Unknown";
    default: return state;
  }
};

export const EnginesTable: React.FC = () => {
  const {
    engines, connectedWorkspace,
    enabledEngineIds, toggleEngineEnabled,
  } = useApp();

  // Filter: show DuckDB always, show Databricks only when a workspace is connected
  const visibleEngines = engines.filter(e =>
    e.engine_type === "duckdb" || (e.engine_type === "databricks_sql" && connectedWorkspace !== null)
  );

  // Count only visible enabled engines
  const visibleEnabledCount = visibleEngines.filter(e => enabledEngineIds.has(e.id)).length;

  const mode: "none" | "single" | "smart" =
    visibleEnabledCount === 0 ? "none" : visibleEnabledCount === 1 ? "single" : "smart";

  const formatSpecs = (e: typeof engines[0]) => {
    if (e.engine_type === "duckdb") {
      return `${e.config.memory_gb} GB / ${e.config.cpu_count} CPU`;
    }
    return e.config.cluster_size ?? "";
  };

  const formatType = (e: typeof engines[0]) => {
    if (e.engine_type === "duckdb") return "DuckDB";
    return "Databricks SQL";
  };

  const modeIndicators = [
    { key: "single", label: "Single Engine" },
    { key: "smart", label: "Smart Routing" },
  ] as const;

  return (
    <div className="text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
          <Server size={12} className="text-primary shrink-0" />
          <span className="font-semibold text-foreground">Engines</span>
          {!connectedWorkspace && (
            <span className="text-[10px] text-muted-foreground">(No Databricks workspace)</span>
          )}
        </div>

        {/* Mode indicator badges */}
        <div className="px-3 py-2 flex items-center gap-2">
          <div className="flex gap-1 flex-1">
            {modeIndicators.map(ind => {
              const isActive = mode === ind.key;
              return (
                <div
                  key={ind.key}
                  className={`flex-1 px-2 py-1 rounded text-[10px] font-medium border text-center select-none ${
                    isActive
                      ? "bg-primary/10 text-primary border-primary"
                      : "bg-muted/30 text-muted-foreground border-border opacity-50"
                  }`}
                >
                  {ind.label}
                </div>
              );
            })}
          </div>
        </div>

        {visibleEngines.length === 0 ? (
          <div className="px-3 py-3 text-muted-foreground text-[11px]">No engines available.</div>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-muted">
                <th className="w-7 px-2 py-1 border-b border-border"></th>
                <th className="text-left px-2 py-1 border-b border-border">Type</th>
                <th className="text-left px-2 py-1 border-b border-border">Specs</th>
              </tr>
            </thead>
            <tbody>
              {visibleEngines.map(e => (
                <tr key={e.id} className="even:bg-card hover:bg-muted/50">
                  <td className="px-2 py-1 border-b border-border text-center">
                    <input
                      type="checkbox"
                      checked={enabledEngineIds.has(e.id)}
                      onChange={() => toggleEngineEnabled(e.id)}
                      className="accent-primary"
                    />
                  </td>
                  <td className="px-2 py-1 border-b border-border text-foreground font-medium">
                    <span className="flex items-center gap-1.5">
                      <span
                        className={`inline-block w-[6px] h-[6px] rounded-full shrink-0 ${runtimeStateStyle(e.runtime_state)}`}
                        title={runtimeStateLabel(e.runtime_state)}
                      />
                      {formatType(e)}
                    </span>
                  </td>
                  <td className="px-2 py-1 border-b border-border text-muted-foreground">
                    {formatSpecs(e)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
};
