import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { CurrentSettings } from "./CurrentSettings";
import { ProfileSelector } from "./ProfileSelector";
import { EnginesTable } from "./EnginesTable";
import { EnginesManagement } from "./EnginesManagement";
import { Database, Lock } from "lucide-react";

type RightPanelTab = "routing" | "engines";

export const RightPanel: React.FC = () => {
  const {
    routingMode,
    routingSettings, updateRoutingSettings,
    logSettings, updateLogSettings,
    benchmarkRunning,
  } = useApp();

  const [activeTab, setActiveTab] = useState<RightPanelTab>("routing");

  const isBenchmark = routingMode === "benchmark";
  const isSingle = routingMode === "single";

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Current Settings — always visible, read-only */}
      <CurrentSettings />

      {/* Profile Selector — above tabs, applies to both Routing and Engines */}
      {!isBenchmark && <ProfileSelector />}

      {/* Tab bar */}
      <div className="flex border-b border-panel-border shrink-0">
        <button
          onClick={() => setActiveTab("routing")}
          className={`flex-1 py-1.5 text-[11px] font-medium transition-colors ${
            activeTab === "routing"
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Routing
        </button>
        <button
          onClick={() => setActiveTab("engines")}
          className={`flex-1 py-1.5 text-[11px] font-medium transition-colors ${
            activeTab === "engines"
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Engines
        </button>
      </div>

      {activeTab === "engines" ? (
        <EnginesManagement />
      ) : (
        <>
          {/* Lock banner when benchmark is running */}
          {benchmarkRunning && (
            <div className="px-3 py-2 bg-amber-50 border-b-2 border-amber-200 flex items-center gap-2">
              <Lock size={12} className="text-amber-600 shrink-0" />
              <span className="text-[11px] text-amber-700 font-medium">
                Settings locked while benchmark is running
              </span>
            </div>
          )}

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
                  { value: 0.2, label: "High Performance" },
                  { value: 0.5, label: "Balanced" },
                  { value: 0.8, label: "Low Cost" },
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
        </>
      )}
    </div>
  );
};
