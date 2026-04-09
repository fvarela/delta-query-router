import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { CurrentSettings } from "./CurrentSettings";
import { ProfileSelector } from "./ProfileSelector";
import { EnginesTable } from "./EnginesTable";
import { Save, SaveAll, Undo2 } from "lucide-react";

export const RightPanel: React.FC = () => {
  const {
    routingMode,
    routingSettings, updateRoutingSettings,
    hasUnsavedChanges, saveRoutingConfig, rollbackRoutingConfig,
    activeProfileId, saveProfileAs,
  } = useApp();

  const isBenchmark = routingMode === "benchmark";

  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState("");
  const handleSaveAs = () => {
    const name = saveAsName.trim();
    if (!name) return;
    saveProfileAs(name);
    setSaveAsName("");
    setSaveAsOpen(false);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Current Settings — always visible, read-only */}
      <CurrentSettings />

      {/* Profile Selector — between CurrentSettings and routing mode (hidden in benchmark mode) */}
      {!isBenchmark && <ProfileSelector />}

      <div className="flex-1 overflow-y-auto">
        <EnginesTable />

        {/* Routing Priority — hidden in benchmark mode */}
        {!isBenchmark && (
        <div className="px-3 py-2.5 border-t border-panel-border">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Routing Priority</span>
          </div>
          <div className="flex rounded-md border border-border overflow-hidden">
            {[
              { value: 0, label: "High Performance" },
              { value: 0.5, label: "Balanced" },
              { value: 1, label: "Low Cost" },
            ].map(({ value, label }) => {
              const isActive = Math.abs(routingSettings.cost_weight - value) < 0.01;
              return (
                <button
                  key={value}
                  onClick={() => updateRoutingSettings({ cost_weight: value, fit_weight: 1 - value })}
                  className={`flex-1 py-1.5 text-[10px] font-medium transition-colors border-r border-border last:border-r-0 ${
                    isActive
                      ? "bg-primary text-primary-foreground"
                      : "bg-card text-muted-foreground hover:bg-muted/50"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
        )}
      </div>

      {/* Save / Save As / Rollback bar — fixed at bottom (hidden in benchmark mode) */}
      {!isBenchmark && (hasUnsavedChanges || saveAsOpen) && (
        <div className="border-t border-panel-border bg-card px-3 py-2 shrink-0">
          {/* Save As inline form */}
          {saveAsOpen ? (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <input
                  autoFocus
                  type="text"
                  value={saveAsName}
                  onChange={e => setSaveAsName(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter") handleSaveAs();
                    if (e.key === "Escape") { setSaveAsOpen(false); setSaveAsName(""); }
                  }}
                  placeholder="Profile name..."
                  className="flex-1 px-2 py-1 text-[11px] bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                  onClick={handleSaveAs}
                  disabled={!saveAsName.trim()}
                  className="px-2 py-1 rounded text-[10px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  Create
                </button>
                <button
                  onClick={() => { setSaveAsOpen(false); setSaveAsName(""); }}
                  className="px-2 py-1 rounded text-[10px] font-medium border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex-1 text-[10px] text-amber-600 font-medium">
                {activeProfileId ? "Modified" : "Not saved"}
              </div>
              <button
                onClick={rollbackRoutingConfig}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
              >
                <Undo2 size={10} />
                Rollback
              </button>
              {activeProfileId && (
                <button
                  onClick={saveRoutingConfig}
                  className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  <Save size={10} />
                  Save
                </button>
              )}
              <button
                onClick={() => setSaveAsOpen(true)}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-medium border border-primary text-primary hover:bg-primary/10 transition-colors"
              >
                <SaveAll size={10} />
                Save As...
              </button>
            </div>
          )}
        </div>
      )}

    </div>
  );
};
