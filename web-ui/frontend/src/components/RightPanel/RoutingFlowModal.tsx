import React from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Modal explaining the Smart Routing decision pipeline.
 * Opened via "How Routing Works" link in the Routing tab.
 */
export const RoutingFlowModal: React.FC<Props> = ({ open, onClose }) => {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-background border border-border rounded-lg shadow-lg w-[520px] max-h-[90vh] flex flex-col text-[12px]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
          <span className="font-semibold text-foreground text-[14px]">
            How Smart Routing Works
          </span>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Intro */}
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            When multiple engines are enabled, Smart Routing automatically
            selects the best engine for each query. Here's how it decides:
          </p>

          {/* Flowchart */}
          <div className="space-y-0">
            {/* Step 1: Query */}
            <FlowNode
              label="Incoming Query"
              description="SQL is parsed and analyzed for complexity, tables, joins, aggregations"
              color="primary"
            />
            <FlowArrow />

            {/* Step 2: System Rules */}
            <FlowNode
              label="System Rules"
              description="Built-in constraints that always apply. Governed tables (row-level security, column masks), VIEWs, and foreign/federated tables are routed to Databricks automatically."
              color="muted"
              badge="Always applied"
            />
            <FlowArrow />

            {/* Step 3: If-Then Rules */}
            <FlowNode
              label="If-Then Rules"
              description="User-defined rules that filter engines based on table name, data size, or query complexity. Evaluated in priority order."
              color="primary"
              badge="Configurable"
            />
            <FlowArrow label="If only 1 engine remains → route directly" />

            {/* Step 4: ML Models (parallel) */}
            <div className="flex gap-3">
              <div className="flex-1">
                <FlowNode
                  label="Latency Model"
                  description="Predicts compute time per engine (ms). I/O latency and cold-start are added separately."
                  color="blue"
                  badge="ML"
                  compact
                />
              </div>
              <div className="flex items-center text-[10px] text-muted-foreground font-mono shrink-0">
                +
              </div>
              <div className="flex-1">
                <FlowNode
                  label="Cost Model"
                  description="Predicts execution cost per engine (USD). Formula-based by default, ML optional."
                  color="emerald"
                  badge="ML / Formula"
                  compact
                />
              </div>
            </div>
            <FlowArrow />

            {/* Step 5: Optimization Priority */}
            <FlowNode
              label="Optimization Priority"
              description={
                "Combines latency and cost scores using your chosen weights.\n" +
                "weighted_score = w_latency × latency_score + w_cost × cost_score\n" +
                "The slider controls the balance between speed and cost."
              }
              color="amber"
              badge="Your preference"
            />
            <FlowArrow />

            {/* Step 6: Engine Selection */}
            <FlowNode
              label="Select Best Engine"
              description="The engine with the lowest weighted score wins. If no ML model is active, falls back to engine preference order."
              color="primary"
            />
          </div>

          {/* Storage Latency explanation */}
          <div className="mt-4 p-3 bg-muted/30 rounded border border-border">
            <h4 className="font-semibold text-foreground text-[11px] mb-1">
              About Storage Latency Probes
            </h4>
            <p className="text-[10px] text-muted-foreground leading-relaxed">
              DuckDB reads data directly from cloud storage (S3, ADLS). The
              latency of these reads depends on where DuckDB is deployed
              relative to the data — running locally vs. in the same cloud
              region makes a huge difference.
            </p>
            <p className="text-[10px] text-muted-foreground leading-relaxed mt-1">
              Storage probes measure this I/O latency. The latency model uses
              probe results to predict total query time:{" "}
              <span className="font-mono text-foreground">
                total = compute_time + io_latency + cold_start
              </span>
              . Re-run probes after redeploying to a new location.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-1.5 border border-border rounded text-[11px] text-foreground hover:bg-muted"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

/* ── Sub-components ──────────────────────────────────────────── */

interface FlowNodeProps {
  label: string;
  description: string;
  color: "primary" | "muted" | "blue" | "emerald" | "amber";
  badge?: string;
  compact?: boolean;
}

const colorMap = {
  primary: {
    border: "border-primary/40",
    bg: "bg-primary/5",
    badge: "bg-primary/15 text-primary",
    dot: "bg-primary",
  },
  muted: {
    border: "border-border",
    bg: "bg-muted/30",
    badge: "bg-muted text-muted-foreground",
    dot: "bg-muted-foreground",
  },
  blue: {
    border: "border-blue-500/40",
    bg: "bg-blue-500/5",
    badge: "bg-blue-500/15 text-blue-500",
    dot: "bg-blue-500",
  },
  emerald: {
    border: "border-emerald-500/40",
    bg: "bg-emerald-500/5",
    badge: "bg-emerald-500/15 text-emerald-500",
    dot: "bg-emerald-500",
  },
  amber: {
    border: "border-amber-500/40",
    bg: "bg-amber-500/5",
    badge: "bg-amber-500/15 text-amber-500",
    dot: "bg-amber-500",
  },
};

const FlowNode: React.FC<FlowNodeProps> = ({
  label,
  description,
  color,
  badge,
  compact,
}) => {
  const c = colorMap[color];
  return (
    <div
      className={`border ${c.border} ${c.bg} rounded-md ${compact ? "px-2.5 py-2" : "px-3 py-2.5"}`}
    >
      <div className="flex items-center gap-2 mb-0.5">
        <div className={`w-1.5 h-1.5 rounded-full ${c.dot} shrink-0`} />
        <span
          className={`font-semibold text-foreground ${compact ? "text-[10px]" : "text-[11px]"}`}
        >
          {label}
        </span>
        {badge && (
          <span
            className={`text-[8px] px-1 py-0.5 rounded font-medium ${c.badge}`}
          >
            {badge}
          </span>
        )}
      </div>
      <p
        className={`text-muted-foreground leading-relaxed ml-3.5 whitespace-pre-line ${compact ? "text-[9px]" : "text-[10px]"}`}
      >
        {description}
      </p>
    </div>
  );
};

const FlowArrow: React.FC<{ label?: string }> = ({ label }) => (
  <div className="flex flex-col items-center py-1">
    <div className="w-px h-3 bg-border" />
    <div className="text-[8px] text-muted-foreground">▼</div>
    {label && (
      <div className="text-[9px] text-muted-foreground italic mt-0.5 text-center px-4">
        {label}
      </div>
    )}
  </div>
);
