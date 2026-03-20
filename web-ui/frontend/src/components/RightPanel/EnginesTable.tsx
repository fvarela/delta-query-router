import React from "react";
import { useApp } from "@/contexts/AppContext";

export const EnginesTable: React.FC = () => {
  const {
    engines, connectedWorkspace,
    enabledEngineIds, toggleEngineEnabled,
  } = useApp();

  // Filter: show DuckDB always, show Databricks only when a workspace is connected
  const visibleEngines = engines.filter(e =>
    e.engine_type === "duckdb" || (e.engine_type === "databricks_sql" && connectedWorkspace !== null)
  );

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

  return (
    <div className="text-[12px]">
      <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
        <span className="font-semibold text-foreground">Engines</span>
        {!connectedWorkspace && (
          <span className="text-[10px] text-muted-foreground italic">No Databricks workspace connected</span>
        )}
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
                  {formatType(e)}
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
