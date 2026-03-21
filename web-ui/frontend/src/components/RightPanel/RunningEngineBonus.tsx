import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { TrendingUp, ChevronDown, ChevronRight, Info, RotateCcw } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

const DEFAULT_DUCKDB = 0.05;
const DEFAULT_DATABRICKS = 0.15;

export const RunningEngineBonus: React.FC = () => {
  const { routingSettings, updateRoutingSettings, runMode } = useApp();
  const [expanded, setExpanded] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);

  // Only show in smart routing (multi-engine) mode
  if (runMode !== "multi") return null;

  const duckdbBonus = routingSettings.running_bonus_duckdb;
  const databricksBonus = routingSettings.running_bonus_databricks;

  const isDefault =
    duckdbBonus === DEFAULT_DUCKDB && databricksBonus === DEFAULT_DATABRICKS;

  const handleDuckdbChange = (val: string) => {
    const num = parseFloat(val);
    if (!isNaN(num) && num >= 0 && num <= 1) {
      updateRoutingSettings({ running_bonus_duckdb: num });
    }
  };

  const handleDatabricksChange = (val: string) => {
    const num = parseFloat(val);
    if (!isNaN(num) && num >= 0 && num <= 1) {
      updateRoutingSettings({ running_bonus_databricks: num });
    }
  };

  const handleReset = () => {
    updateRoutingSettings({
      running_bonus_duckdb: DEFAULT_DUCKDB,
      running_bonus_databricks: DEFAULT_DATABRICKS,
    });
  };

  return (
    <>
      <div className="text-[12px]">
        <div className="w-full px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 hover:bg-muted/50">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 flex-1 min-w-0"
          >
            {expanded ? (
              <ChevronDown size={12} className="text-muted-foreground shrink-0" />
            ) : (
              <ChevronRight size={12} className="text-muted-foreground shrink-0" />
            )}
            <TrendingUp size={12} className="text-primary shrink-0" />
            <span className="font-semibold text-foreground">Running Engine Bonus</span>
            <span className="text-[10px] text-muted-foreground">
              (DuckDB {duckdbBonus.toFixed(2)}, Databricks {databricksBonus.toFixed(2)})
            </span>
          </button>
          <button
            onClick={() => setShowInfoModal(true)}
            className="text-muted-foreground hover:text-primary transition-colors shrink-0"
            title="How Running Engine Bonus works"
          >
            <Info size={12} />
          </button>
        </div>

        {expanded && (
          <div className="px-3 py-2 space-y-2">
            {/* DuckDB bonus */}
            <div className="flex items-center gap-2">
              <label className="text-[11px] text-muted-foreground w-[80px] shrink-0">
                DuckDB
              </label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={duckdbBonus}
                onChange={(e) => handleDuckdbChange(e.target.value)}
                className="w-[72px] px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground text-right"
              />
              <span className="text-[9px] text-muted-foreground">0 = no bonus · 1 = max</span>
            </div>

            {/* Databricks bonus */}
            <div className="flex items-center gap-2">
              <label className="text-[11px] text-muted-foreground w-[80px] shrink-0">
                Databricks
              </label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={databricksBonus}
                onChange={(e) => handleDatabricksChange(e.target.value)}
                className="w-[72px] px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground text-right"
              />
            </div>

            {/* Reset to Defaults */}
            {!isDefault && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                <RotateCcw size={10} />
                <span>Reset to Defaults</span>
              </button>
            )}
          </div>
        )}
      </div>

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="bonus"
      />
    </>
  );
};
