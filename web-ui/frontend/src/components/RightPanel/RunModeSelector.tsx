import React from "react";
import { useApp } from "@/contexts/AppContext";

export const RunModeSelector: React.FC = () => {
  const { runMode, enabledEngineIds, engines, connectedWorkspace } = useApp();

  // Count only visible enabled engines
  const visibleEnabledCount = engines.filter(e => {
    if (!enabledEngineIds.has(e.id)) return false;
    if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
    return true;
  }).length;

  const mode: "none" | "direct" | "smart" =
    visibleEnabledCount === 0 ? "none" : visibleEnabledCount === 1 ? "direct" : "smart";

  const indicators = [
    { key: "direct", label: "Direct" },
    { key: "smart", label: "Smart Routing" },
  ] as const;

  return (
    <div className="text-[12px]">
      <div className="px-3 py-1.5 border-b border-panel-border">
        <span className="font-semibold text-foreground">Routing Mode</span>
      </div>
      <div className="px-3 py-2 flex gap-1">
        {indicators.map(ind => {
          const isActive = mode === ind.key;
          return (
            <div
              key={ind.key}
              className={`flex-1 px-3 py-1.5 rounded text-[11px] font-medium border text-center select-none ${
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
      {mode === "smart" && (
        <div className="px-3 pb-2">
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span>Query</span>
            <span className="text-muted-foreground/50">&rarr;</span>
            <span>Rules</span>
            <span className="text-muted-foreground/50">&rarr;</span>
            <span>ML Model</span>
            <span className="text-muted-foreground/50">&rarr;</span>
            <span>Engine</span>
          </div>
        </div>
      )}
    </div>
  );
};
