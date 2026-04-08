import React from "react";
import { useApp } from "@/contexts/AppContext";
import { Zap, Scale, DollarSign, Brain, Radio, Bookmark, Cloud, AlertTriangle, CheckCircle2 } from "lucide-react";

const priorityLabel = (costWeight: number): { label: string; icon: React.ReactNode } => {
  if (costWeight < 0.01) return { label: "High Performance", icon: <Zap size={11} className="text-amber-500" /> };
  if (costWeight > 0.99) return { label: "Low Cost", icon: <DollarSign size={11} className="text-emerald-500" /> };
  return { label: "Balanced", icon: <Scale size={11} className="text-blue-500" /> };
};

/** Workspace dependency indicator — shows satisfied/unsatisfied state */
const WorkspaceDep: React.FC<{
  binding: { workspaceName: string; workspaceUrl: string } | null;
  connectedWorkspace: { url: string } | null;
}> = ({ binding, connectedWorkspace }) => {
  if (!binding) return null;

  const isSatisfied = connectedWorkspace !== null && connectedWorkspace.url === binding.workspaceUrl;

  return (
    <>
      <span className="text-[10px] text-muted-foreground/40">|</span>
      <span className="flex items-center gap-1 text-[10px]">
        {isSatisfied ? (
          <CheckCircle2 size={9} className="text-emerald-500" />
        ) : (
          <AlertTriangle size={9} className="text-amber-500" />
        )}
        <Cloud size={9} className={isSatisfied ? "text-emerald-500" : "text-amber-500"} />
        <span className={`truncate max-w-[120px] ${isSatisfied ? "text-muted-foreground" : "text-amber-600"}`}>
          {binding.workspaceName}
        </span>
      </span>
    </>
  );
};

export const CurrentSettings: React.FC = () => {
  const { routingMode, singleEngineId, engines, enabledEngineIds, connectedWorkspace, routingSettings, activeModelId, models, activeProfileName, hasUnsavedChanges, profileWorkspaceBinding } = useApp();

  const activeModel = models.find(m => m.id === activeModelId);
  const priority = priorityLabel(routingSettings.cost_weight);

  if (routingMode === "single") {
    const selectedEngine = engines.find(e => e.id === singleEngineId);

    return (
      <div className="bg-[hsl(217,91%,97%)] border-b-2 border-[hsl(217,91%,85%)]">
        <div className="px-3 py-2.5 space-y-2">
          {/* Profile name badge */}
          {activeProfileName && (
            <div className="flex items-center gap-1.5">
              <Bookmark size={10} className="text-[hsl(217,91%,60%)] shrink-0" />
              <span className="text-[10px] font-medium text-[hsl(217,91%,45%)] truncate">{activeProfileName}</span>
              {hasUnsavedChanges && <span className="text-[9px] text-amber-600 font-medium">*</span>}
            </div>
          )}

          {/* Row 1: Single engine info */}
          <div className="flex items-start gap-2">
            <Radio size={11} className="text-[hsl(217,91%,60%)] mt-[2px] shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-semibold text-foreground">Single Engine</span>
              </div>
              {selectedEngine ? (
                <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                  {selectedEngine.display_name}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground/60 mt-0.5 italic">
                  No engine selected
                </div>
              )}
            </div>
          </div>

          {/* Row 2: Priority + Workspace dependency */}
          <div className="flex items-center gap-3 pl-[19px] flex-wrap">
            <span className="flex items-center gap-1 text-[10px]">
              {priority.icon}
              <span className="font-medium text-foreground">{priority.label}</span>
            </span>
            <WorkspaceDep binding={profileWorkspaceBinding} connectedWorkspace={connectedWorkspace} />
          </div>
        </div>
      </div>
    );
  }

  // Smart Routing mode
  const modelEngines = activeModel
    ? engines.filter(e => activeModel.linked_engines.includes(e.id) && enabledEngineIds.has(e.id))
    : [];

  // Filter out unavailable Databricks engines for display (when no workspace connected)
  const availableModelEngines = modelEngines.filter(e => {
    if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
    return true;
  });

  return (
    <div className="bg-[hsl(217,91%,97%)] border-b-2 border-[hsl(217,91%,85%)]">
      <div className="px-3 py-2.5 space-y-2">
        {/* Profile name badge */}
        {activeProfileName && (
          <div className="flex items-center gap-1.5">
            <Bookmark size={10} className="text-[hsl(217,91%,60%)] shrink-0" />
            <span className="text-[10px] font-medium text-[hsl(217,91%,45%)] truncate">{activeProfileName}</span>
            {hasUnsavedChanges && <span className="text-[9px] text-amber-600 font-medium">*</span>}
          </div>
        )}

        {/* Row 1: Smart Routing + engine names */}
        <div className="flex items-start gap-2">
          <Radio size={11} className="text-[hsl(217,91%,60%)] mt-[2px] shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-semibold text-[hsl(217,91%,45%)]">
                Smart Routing
              </span>
              {availableModelEngines.length > 0 && (
                <span className="text-[10px] text-muted-foreground">
                  ({availableModelEngines.length} engine{availableModelEngines.length !== 1 ? "s" : ""})
                </span>
              )}
            </div>
            {availableModelEngines.length > 0 && (
              <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                {availableModelEngines.map(e => e.display_name).join(" · ")}
              </div>
            )}
          </div>
        </div>

        {/* Row 2: Priority + Model + Workspace dependency — compact inline */}
        <div className="flex items-center gap-3 pl-[19px] flex-wrap">
          <span className="flex items-center gap-1 text-[10px]">
            {priority.icon}
            <span className="font-medium text-foreground">{priority.label}</span>
          </span>
          <span className="text-[10px] text-muted-foreground/40">|</span>
          <span className="flex items-center gap-1 text-[10px]">
            {activeModel ? (
              <>
                <Brain size={10} className="text-[hsl(217,91%,60%)]" />
                <span className="font-medium text-foreground">Model #{activeModel.id}</span>
                <span className="text-muted-foreground">(R²={activeModel.latency_model.r_squared})</span>
              </>
            ) : (
              <>
                <Brain size={10} className="text-muted-foreground/40" />
                <span className="text-muted-foreground italic">No model</span>
              </>
            )}
          </span>
          <WorkspaceDep binding={profileWorkspaceBinding} connectedWorkspace={connectedWorkspace} />
        </div>
      </div>
    </div>
  );
};
