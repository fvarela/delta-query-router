import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { ChevronDown, ChevronRight } from "lucide-react";

export const MLModelSelector: React.FC = () => {
  const { models, reloadModels, activeModelId, setActiveModelId, enabledEngineIds, engines } = useApp();
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Engine IDs as string keys (mock models use string engine IDs like "duckdb:2gb-2cpu")
  const enabledEngineStringIds = engines
    .filter(e => enabledEngineIds.has(e.id))
    .map(e => {
      if (e.engine_type === "duckdb") {
        const mem = e.config.memory_gb;
        const cpu = e.config.cpu_count;
        return `duckdb:${mem}gb-${cpu}cpu`;
      }
      return `databricks:serverless-${e.display_name.split(" ").pop()?.toLowerCase()}`;
    });

  // A model is compatible if ALL its linked_engines are in the currently enabled set
  const isModelCompatible = (linkedEngines: string[]) =>
    linkedEngines.every(le => enabledEngineStringIds.includes(le));

  const compatibleCount = models.filter(m => isModelCompatible(m.linked_engines)).length;

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

  return (
    <div className="text-[12px]">
      <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5">
        <span className="font-semibold text-foreground">ML Models</span>
        <span className="text-[10px] text-muted-foreground">
          ({compatibleCount}/{models.length} available)
        </span>
      </div>

      <div className="divide-y divide-border">
        {models.map(m => {
          const compatible = isModelCompatible(m.linked_engines);
          const isActive = activeModelId === m.id;
          const isExpanded = expandedId === m.id;

          return (
            <div key={m.id} className={`px-3 py-2 ${!compatible ? "opacity-40" : ""}`}>
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  name="active-model"
                  checked={isActive}
                  disabled={!compatible}
                  onChange={() => handleActivate(m.id)}
                  className="accent-primary shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <button onClick={() => setExpandedId(isExpanded ? null : m.id)} className="text-muted-foreground">
                      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </button>
                    <span className="text-foreground font-medium truncate">Model #{m.id}</span>
                    {isActive && <span className="text-[9px] bg-primary/20 text-primary px-1 rounded">Active</span>}
                    {!compatible && <span className="text-[9px] text-status-warning">Incompatible</span>}
                  </div>
                  <div className="text-[10px] text-muted-foreground ml-5">
                    {m.linked_engines.length} engines · {m.benchmark_count ?? 0} benchmarks · R²={m.accuracy_metrics.r_squared.toFixed(2)}
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div className="mt-1.5 ml-5 text-[10px] text-muted-foreground space-y-0.5">
                  <p>Path: {m.model_path}</p>
                  <p>R²: {m.accuracy_metrics.r_squared.toFixed(3)} | MAE: {m.accuracy_metrics.mae_ms}ms</p>
                  <p>Created: {new Date(m.created_at).toLocaleString()}</p>
                  <p>Engines: {m.linked_engines.join(", ")}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
