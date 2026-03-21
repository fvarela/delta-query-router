import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { Scale, ChevronDown, ChevronRight, Info } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

/** Cost vs Latency Priority — discrete 3-step toggle.
 *  Visible only in Smart Routing mode.
 *  Maps to routingSettings.latency_weight / cost_weight (sum to 1.0).
 */

const PRESETS = [
  { label: "Low Cost", latency_weight: 0.2, description: "Prefer cheaper engines" },
  { label: "Balanced", latency_weight: 0.5, description: "Equal weight" },
  { label: "Fast", latency_weight: 0.8, description: "Prefer faster engines" },
] as const;

export const SpeedCostSlider: React.FC = () => {
  const { routingSettings, updateRoutingSettings, runMode, activeModelId } = useApp();
  const [expanded, setExpanded] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);

  // Only show in smart routing (multi-engine) mode
  if (runMode !== "multi") return null;

  const handleSelect = (latency_weight: number) => {
    updateRoutingSettings({ latency_weight, cost_weight: 1 - latency_weight });
  };

  // Find the closest preset to current value
  const activeIdx = PRESETS.reduce((bestIdx, preset, idx) => {
    const bestDist = Math.abs(PRESETS[bestIdx].latency_weight - routingSettings.latency_weight);
    const thisDist = Math.abs(preset.latency_weight - routingSettings.latency_weight);
    return thisDist < bestDist ? idx : bestIdx;
  }, 0);

  const activeLabel = PRESETS[activeIdx].label;

  return (
    <>
    <div className="text-[12px]">
      <div
        className="w-full px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 hover:bg-muted/50"
      >
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 flex-1 min-w-0"
        >
          {expanded ? <ChevronDown size={12} className="text-muted-foreground shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground shrink-0" />}
          <Scale size={12} className="text-primary shrink-0" />
          <span className="font-semibold text-foreground">Cost vs Latency Priority</span>
          <span className="text-[10px] text-muted-foreground">({activeLabel})</span>
        </button>
        <button
          onClick={() => setShowInfoModal(true)}
          className="text-muted-foreground hover:text-primary transition-colors shrink-0"
          title="How Cost vs Latency Priority works"
        >
          <Info size={12} />
        </button>
      </div>

      {expanded && (
        <div className="px-3 py-2 space-y-2">
          <div className="flex gap-1">
            {PRESETS.map((preset, idx) => {
              const isActive = idx === activeIdx;
              return (
                <button
                  key={preset.label}
                  onClick={() => handleSelect(preset.latency_weight)}
                  title={preset.description}
                  className={`flex-1 px-1.5 py-1.5 rounded text-[10px] font-medium border text-center transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary border-primary"
                      : "bg-muted/30 text-muted-foreground border-border hover:bg-muted/60"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
          {activeModelId == null && (
            <p className="text-[10px] text-muted-foreground">
              No ML model active — routing uses rules only. Priority weighting applies once a model is selected.
            </p>
          )}
        </div>
      )}
    </div>

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="priority"
      />
    </>
  );
};

/** Icon for the collapsible section header */
export const OptimizationIcon = Scale;
