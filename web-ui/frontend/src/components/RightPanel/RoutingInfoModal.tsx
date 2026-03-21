import React from "react";
import { X, ArrowDown } from "lucide-react";

/** Which pipeline stage to highlight in the diagram. */
export type RoutingStage = "system" | "rules" | "ml" | "priority" | "bonus" | "storage";

interface Props {
  open: boolean;
  onClose: () => void;
  stage: RoutingStage;
}

/* ── Stage metadata ──────────────────────────────────────────── */

interface StageInfo {
  id: RoutingStage;
  label: string;
}

const PIPELINE_STAGES: StageInfo[] = [
  { id: "system", label: "System Rules" },
  { id: "rules", label: "If-Then Rules" },
  { id: "ml", label: "ML Models" },
  { id: "priority", label: "Cost vs Latency Priority" },
  { id: "bonus", label: "Running Engine Bonus" },
];

/* ── Detail content per stage ────────────────────────────────── */

interface DetailContent {
  title: string;
  sections: { heading?: string; text: string }[];
}

const DETAIL_TEXT: Record<RoutingStage, DetailContent> = {
  system: {
    title: "System Rules",
    sections: [
      { text: "Built-in rules that enforce hard constraints before any user-defined logic runs. Cannot be edited or disabled." },
      { heading: "Governed tables", text: "Tables with row-level security or column masking are always routed to Databricks." },
      { heading: "VIEWs & federated tables", text: "SQL Server, Snowflake, and other foreign data sources are Databricks-only. VIEWs follow the same rule." },
      { heading: "Always first", text: "System rules run before If-Then Rules, ML models, and priority weighting. If a system rule matches, no further stages are evaluated." },
    ],
  },
  rules: {
    title: "If-Then Rules",
    sections: [
      { text: "User-defined rules that force or filter engine selection based on table name, data size, or query complexity. Evaluated in priority order." },
      { heading: "Short-circuit", text: "If only one engine remains after rules, it is selected immediately — ML models and priority weighting are skipped." },
      { heading: "No model needed", text: "Rules work independently of ML models. System rules (governed tables, VIEWs, federated tables) always run first." },
    ],
  },
  ml: {
    title: "ML Models",
    sections: [
      { text: "Each model bundles a latency sub-model and a cost sub-model, trained together on benchmark data." },
      { heading: "Latency formula", text: "Total latency = predicted compute time + I/O latency (from storage probes) + cold-start time." },
      { heading: "Compatibility", text: "A model is compatible only if it covers all currently enabled engines. If no model is active, routing falls back to rules only." },
    ],
  },
  priority: {
    title: "Cost vs Latency Priority",
    sections: [
      { text: "Balances latency vs. cost predictions from the ML models using a weighted score." },
      { heading: "Presets", text: "Low Cost (cost-weighted 80%), Balanced (50/50), Fast (latency-weighted 80%). The engine with the lowest combined score wins." },
      { heading: "Requires a model", text: "Without an active ML model, there are no predictions to weight — routing relies on rules alone." },
    ],
  },
  bonus: {
    title: "Running Engine Bonus",
    sections: [
      { text: "Applies a flat score reduction to engines that are currently running, nudging the router toward them instead of starting stopped engines." },
      { heading: "Why it matters", text: "Starting a stopped Databricks warehouse incurs cold-start latency and commits to a billing period. Routing to an already-running warehouse is nearly free." },
      { heading: "Range", text: "Each bonus is a value from 0 (no bonus) to 1 (max bonus). Databricks defaults higher (0.15) than DuckDB (0.05) because the cost difference between running and stopped is much larger." },
    ],
  },
  storage: {
    title: "Storage Latency",
    sections: [
      { text: "Measures I/O latency from DuckDB engines to cloud storage locations (S3, ADLS, GCS). Feeds into the ML latency model for accurate predictions." },
      { heading: "When to re-run", text: "After redeploying DuckDB or moving data to a different storage account or region." },
      { heading: "Color coding", text: "Green (\u226450 ms), amber (50\u2013150 ms), red (>150 ms)." },
    ],
  },
};

/* ── Component ───────────────────────────────────────────────── */

export const RoutingInfoModal: React.FC<Props> = ({ open, onClose, stage }) => {
  if (!open) return null;

  const detail = DETAIL_TEXT[stage];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-background border border-border rounded-lg shadow-lg w-[420px] max-h-[85vh] flex flex-col text-[12px]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
          <span className="font-semibold text-foreground text-[14px]">
            {detail.title}
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
          <PipelineDiagram highlight={stage} />

          <div className="space-y-2.5">
            {detail.sections.map((s, i) => (
              <div key={i} className="text-[11px] leading-relaxed">
                {s.heading && (
                  <span className="font-semibold text-foreground">{s.heading}: </span>
                )}
                <span className="text-muted-foreground">{s.text}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-border flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 border border-border rounded text-[11px] text-foreground hover:bg-muted"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

/* ── Pipeline Diagram ────────────────────────────────────────── */

const stageStyle = (id: string, highlight: RoutingStage) => {
  const isHighlight = id === highlight;
  if (isHighlight) return "bg-primary/15 border-primary text-primary ring-1 ring-primary/30";
  return "bg-card border-border text-foreground/70";
};

const PipelineDiagram: React.FC<{ highlight: RoutingStage }> = ({ highlight }) => {
  return (
    <div className="px-3 py-2.5 bg-muted/20 rounded-lg border border-border">
      <p className="text-[9px] text-muted-foreground mb-2 uppercase tracking-wider font-medium">
        Routing Pipeline
      </p>
      <div className="flex flex-col items-center gap-0">
        {PIPELINE_STAGES.map((s, idx) => (
          <React.Fragment key={s.id}>
            {idx > 0 && (
              <ArrowDown size={10} className="text-muted-foreground/50" />
            )}

            {/* ML Models row: pipeline box + Storage Latency side-by-side */}
            {s.id === "ml" ? (
              <div className="w-full max-w-[320px] flex items-center gap-2">
                <div className={`flex-1 px-3 py-1.5 rounded border text-center text-[10px] font-medium transition-colors ${stageStyle("ml", highlight)}`}>
                  {s.label}
                </div>
                <div className="w-3 border-t border-dashed border-muted-foreground/40 shrink-0" />
                <div className={`px-2 py-1 rounded border text-[9px] font-medium whitespace-nowrap shrink-0 transition-colors ${stageStyle("storage", highlight)}`}>
                  Storage Latency
                </div>
              </div>
            ) : (
              <div className={`w-full max-w-[220px] px-3 py-1.5 rounded border text-center text-[10px] font-medium transition-colors ${stageStyle(s.id, highlight)}`}>
                {s.label}
              </div>
            )}
          </React.Fragment>
        ))}

        {/* Output indicator — the result of the pipeline */}
        <ArrowDown size={10} className="text-muted-foreground/50" />
        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground font-medium">
          <span>▸</span>
          <span>Selected Engine</span>
        </div>
      </div>
    </div>
  );
};
