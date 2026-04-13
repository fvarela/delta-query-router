import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { CurrentSettings } from "./CurrentSettings";
import { ProfileSelector } from "./ProfileSelector";
import { EnginesTable } from "./EnginesTable";
import { Save, SaveAll, Undo2, Database, Lock } from "lucide-react";

export const RightPanel: React.FC = () => {
  const {
    routingMode,
    routingSettings, updateRoutingSettings,
    logSettings, updateLogSettings,
    hasUnsavedChanges, saveRoutingConfig, rollbackRoutingConfig,
    activeProfileId, saveProfileAs,
    benchmarkRunning,
  } = useApp();

  const isBenchmark = routingMode === "benchmark";
  const isSingle = routingMode === "single";

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

      {/* Lock banner when benchmark is running */}
      {benchmarkRunning && (
        <div className="px-3 py-2 bg-amber-50 border-b-2 border-amber-200 flex items-center gap-2">
          <Lock size={12} className="text-amber-600 shrink-0" />
          <span className="text-[11px] text-amber-700 font-medium">
            Settings locked while benchmark is running
          </span>
        </div>
      )}

      {/* Profile Selector — between CurrentSettings and routing mode (hidden in benchmark mode) */}
      {!isBenchmark && <ProfileSelector />}

      <div className={`flex-1 overflow-y-auto ${benchmarkRunning ? "pointer-events-none opacity-60" : ""}`}>
        <EnginesTable />

        {/* Routing Priority — hidden in benchmark and single engine modes (UX #1) */}
        {!isBenchmark && !isSingle && (
        <div className="px-3 py-2.5 border-t border-panel-border">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Routing Priority</span>
          </div>
          <div className="flex rounded-md border border-border overflow-hidden shadow-sm">
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
                  className={`flex-1 py-1.5 text-[11px] font-medium transition-colors border-r border-border last:border-r-0 ${
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

        {/* Log Retention Settings (Phase 17) */}
        <div className="px-3 py-2.5 border-t border-panel-border">
          <div className="flex items-center gap-1.5 mb-2">
            <Database size={13} strokeWidth={1.5} className="text-muted-foreground" />
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Log Retention</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <label className="text-[10px] text-muted-foreground whitespace-nowrap">Keep</label>
              <input
                type="number"
                min={1}
                max={365}
                value={logSettings.retention_days}
                onChange={e => {
                  const v = parseInt(e.target.value, 10);
                  if (v >= 1) updateLogSettings({ retention_days: v });
                }}
                className="w-14 px-1.5 py-1 text-[11px] bg-background border border-border rounded text-center focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <span className="text-[10px] text-muted-foreground">days</span>
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[10px] text-muted-foreground whitespace-nowrap">Max</label>
              <input
                type="number"
                min={1}
                max={10240}
                value={logSettings.max_size_mb}
                onChange={e => {
                  const v = parseInt(e.target.value, 10);
                  if (v >= 1) updateLogSettings({ max_size_mb: v });
                }}
                className="w-16 px-1.5 py-1 text-[11px] bg-background border border-border rounded text-center focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <span className="text-[10px] text-muted-foreground">MB</span>
            </div>
          </div>
        </div>
      </div>

      {/* Save / Save As / Rollback bar — fixed at bottom (hidden in benchmark mode) */}
      {!isBenchmark && (hasUnsavedChanges || saveAsOpen) && (
        <div className="border-t border-panel-border bg-card px-3 py-2 shrink-0 shadow-section">
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
                  className="flex-1 px-2 py-1 text-[12px] bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                  onClick={handleSaveAs}
                  disabled={!saveAsName.trim()}
                  className="px-2.5 py-1 rounded text-[11px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 shadow-sm"
                >
                  Create
                </button>
                <button
                  onClick={() => { setSaveAsOpen(false); setSaveAsName(""); }}
                  className="px-2.5 py-1 rounded text-[11px] font-medium border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex-1 text-[11px] text-amber-600 font-medium">
                {activeProfileId ? "Modified" : "Not saved"}
              </div>
              <button
                onClick={rollbackRoutingConfig}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
              >
                <Undo2 size={11} />
                Rollback
              </button>
              {activeProfileId && (
                <button
                  onClick={saveRoutingConfig}
                  className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
                >
                  <Save size={11} />
                  Save
                </button>
              )}
              <button
                onClick={() => setSaveAsOpen(true)}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium border border-primary text-primary hover:bg-primary/10 transition-colors"
              >
                <SaveAll size={11} />
                Save As...
              </button>
            </div>
          )}
        </div>
      )}

    </div>
  );
};
