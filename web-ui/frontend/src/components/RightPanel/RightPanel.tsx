import React from "react";
import { useApp } from "@/contexts/AppContext";
import { EnginesTable } from "./EnginesTable";
import { RoutingPipeline } from "./RoutingPipeline";
import { TrainModePanel } from "./TrainModePanel";

export const RightPanel: React.FC = () => {
  const { runMode, panelMode, enabledEngineIds, engines, connectedWorkspace } = useApp();

  // Count only visible enabled engines (Databricks hidden when no workspace)
  const visibleEnabledCount = engines.filter(e => {
    if (!enabledEngineIds.has(e.id)) return false;
    if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
    return true;
  }).length;

  // If in train mode, show the train panel instead of normal routing
  if (panelMode === "train") {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <TrainModePanel />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <EnginesTable />
        {runMode === "multi" ? (
          <>
            <div className="border-t border-panel-border" />
            <RoutingPipeline />
          </>
        ) : (
          <div className="px-3 py-3 text-[11px] text-muted-foreground">
            {visibleEnabledCount === 0 ? (
              <p>Select at least one engine to enable query routing.</p>
            ) : (
              <p>All queries will be sent directly to the selected engine. Select two or more engines to enable Smart Routing with rules and ML-based decisions.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
