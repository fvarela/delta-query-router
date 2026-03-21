import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { ChevronDown, ChevronRight, Trash2, Brain, X, Info } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

export const MLModelSelector: React.FC = () => {
  const { models, reloadModels, activeModelId, setActiveModelId, enabledEngineIds, engines, connectedWorkspace } = useApp();
  const [sectionExpanded, setSectionExpanded] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [detailModelId, setDetailModelId] = useState<number | null>(null);
  const [showInfoModal, setShowInfoModal] = useState(false);

  // Engine IDs as string keys (mock models use string engine IDs like "duckdb:2gb-2cpu")
  // Only include visible engines (Databricks hidden when no workspace connected)
  const enabledEngineStringIds = engines
    .filter(e => {
      if (!enabledEngineIds.has(e.id)) return false;
      if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
      return true;
    })
    .map(e => {
      if (e.engine_type === "duckdb") {
        const mem = e.config.memory_gb;
        const cpu = e.config.cpu_count;
        return `duckdb:${mem}gb-${cpu}cpu`;
      }
      return `databricks:serverless-${e.display_name.split(" ").pop()?.toLowerCase()}`;
    });

  // A model is compatible if ALL currently enabled engines are covered by the model's linked_engines.
  // A model trained on more engines than selected is fine; trained on fewer is not.
  const isModelCompatible = (linkedEngines: string[]) =>
    enabledEngineStringIds.every(ee => linkedEngines.includes(ee));

  const compatibleCount = models.filter(m => isModelCompatible(m.linked_engines)).length;
  const activeModel = activeModelId != null ? models.find(m => m.id === activeModelId) : null;
  const activeIsCompatible = activeModel ? isModelCompatible(activeModel.linked_engines) : false;

  // Header summary text
  const headerSummary = models.length === 0
    ? "none"
    : activeIsCompatible
      ? `${compatibleCount}/${models.length} compatible, 1 active`
      : `${compatibleCount}/${models.length} compatible, none active`;

  const handleActivate = async (id: number) => {
    if (activeModelId === id) {
      await mockApi.deactivateModel(id);
      setActiveModelId(null);
    } else {
      await mockApi.activateModel(id);
      setActiveModelId(id);
    }
    await reloadModels();
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await mockApi.deleteModel(id);
      if (activeModelId === id) setActiveModelId(null);
      await reloadModels();
    } finally {
      setDeletingId(null);
    }
  };

  const detailModel = detailModelId != null ? models.find(m => m.id === detailModelId) : null;

  return (
    <>
      <div className="text-[12px]">
        <div
          className="w-full px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 hover:bg-muted/50"
        >
          <button
            onClick={() => setSectionExpanded(!sectionExpanded)}
            className="flex items-center gap-1.5 flex-1 min-w-0"
          >
            {sectionExpanded ? <ChevronDown size={12} className="text-muted-foreground shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground shrink-0" />}
            <Brain size={12} className="text-primary shrink-0" />
            <span className="font-semibold text-foreground">ML Models</span>
            <span className="text-[10px] text-muted-foreground">
              ({headerSummary})
            </span>
          </button>
          <button
            onClick={() => setShowInfoModal(true)}
            className="text-muted-foreground hover:text-primary transition-colors shrink-0"
            title="How ML Models work"
          >
            <Info size={12} />
          </button>
        </div>

        {sectionExpanded && (
          <>
            {models.length === 0 ? (
              <div className="px-3 py-3 text-[10px] text-muted-foreground italic">
                No models trained yet. Use "Train New Model" to create one.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {models.map(m => {
                  const compatible = isModelCompatible(m.linked_engines);
                  const isActive = activeModelId === m.id;
                  const isDeleting = deletingId === m.id;

                  return (
                    <div key={m.id} className={`px-3 py-2 ${!compatible ? "opacity-40" : ""} ${isDeleting ? "opacity-50" : ""}`}>
                      <div className="flex items-center gap-2">
                        <input
                          type="radio"
                          name="active-model"
                          checked={isActive}
                          disabled={!compatible || isDeleting}
                          onChange={() => handleActivate(m.id)}
                          className="accent-primary shrink-0"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-foreground font-medium truncate">Model #{m.id}</span>
                            {isActive && <span className="text-[9px] bg-primary/20 text-primary px-1 rounded">Active</span>}
                            {!compatible && <span className="text-[9px] text-status-warning">Incompatible</span>}
                          </div>
                          <div className="text-[10px] text-muted-foreground">
                            {m.linked_engines.length} engines · {m.benchmark_count ?? 0} benchmarks
                            <span className="mx-1">·</span>
                            <button
                              onClick={(e) => { e.stopPropagation(); setDetailModelId(m.id); }}
                              className="text-primary/70 hover:text-primary"
                            >
                              View Details
                            </button>
                          </div>
                        </div>
                        <button
                          onClick={() => handleDelete(m.id)}
                          disabled={isDeleting}
                          className="text-muted-foreground hover:text-red-500 shrink-0 p-0.5"
                          title="Delete model"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {/* Guidance when no model is active */}
            {models.length > 0 && !activeIsCompatible && (
              <div className="px-3 py-2 text-[10px] text-muted-foreground border-t border-border">
                {compatibleCount > 0
                  ? "Select a model to enable ML-based routing. Without one, routing uses rules only."
                  : "No models cover all selected engines. Train a new model or adjust engine selection."}
              </div>
            )}
          </>
        )}
      </div>

      {/* Model Detail Modal */}
      {detailModel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background border border-border rounded-lg shadow-lg w-[420px] max-h-[80vh] flex flex-col text-[12px]">
            {/* Header */}
            <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
              <span className="font-semibold text-foreground text-[14px]">Model #{detailModel.id} — Details</span>
              <button onClick={() => setDetailModelId(null)} className="text-muted-foreground hover:text-foreground">
                <X size={16} />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* Overview */}
              <div className="space-y-1 text-[11px]">
                <p className="text-muted-foreground">Created: {new Date(detailModel.created_at).toLocaleString()}</p>
                <p className="text-muted-foreground">Engines: {detailModel.linked_engines.join(", ")}</p>
                <p className="text-muted-foreground">Benchmarks used: {detailModel.benchmark_count ?? 0}</p>
                {detailModel.training_queries != null && (
                  <p className="text-muted-foreground">Training queries: {detailModel.training_queries}</p>
                )}
              </div>

              {/* Latency sub-model */}
              <div>
                <h4 className="font-semibold text-foreground mb-1.5 flex items-center gap-1.5">
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-blue-500/15 text-blue-500">Latency</span>
                  Sub-model
                </h4>
                <div className="bg-muted/30 rounded p-2.5 space-y-1 text-[11px]">
                  <p className="text-foreground">R²: <span className="font-medium">{detailModel.latency_model.r_squared.toFixed(3)}</span></p>
                  {detailModel.latency_model.mae_ms != null && (
                    <p className="text-foreground">MAE: <span className="font-medium">{detailModel.latency_model.mae_ms} ms</span></p>
                  )}
                  <p className="text-muted-foreground text-[10px]">Path: {detailModel.latency_model.model_path}</p>
                </div>
              </div>

              {/* Cost sub-model */}
              <div>
                <h4 className="font-semibold text-foreground mb-1.5 flex items-center gap-1.5">
                  <span className="text-[9px] px-1.5 py-0.5 rounded font-medium bg-emerald-500/15 text-emerald-500">Cost</span>
                  Sub-model
                </h4>
                <div className="bg-muted/30 rounded p-2.5 space-y-1 text-[11px]">
                  <p className="text-foreground">R²: <span className="font-medium">{detailModel.cost_model.r_squared.toFixed(3)}</span></p>
                  {detailModel.cost_model.mae_usd != null && (
                    <p className="text-foreground">MAE: <span className="font-medium">${detailModel.cost_model.mae_usd.toFixed(4)}</span></p>
                  )}
                  <p className="text-muted-foreground text-[10px]">Path: {detailModel.cost_model.model_path}</p>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="px-4 py-3 border-t border-border flex justify-end shrink-0">
              <button
                onClick={() => setDetailModelId(null)}
                className="px-3 py-1.5 border border-border rounded text-[11px] text-foreground"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="ml"
      />
    </>
  );
};
