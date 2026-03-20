import React, { useState, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { ArrowLeft, Zap, CheckCircle2 } from "lucide-react";
import type { Collection, BenchmarkSummary } from "@/types";

export const TrainModePanel: React.FC = () => {
  const {
    setPanelMode, engines, enabledEngineIds, toggleEngineEnabled,
    models, connectedWorkspace,
  } = useApp();

  const [collections, setCollections] = useState<Collection[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState<number | null>(null);
  const [training, setTraining] = useState(false);
  const [trainingStage, setTrainingStage] = useState("");
  const [trainingComplete, setTrainingComplete] = useState(false);

  useEffect(() => {
    mockApi.getCollections().then(setCollections);
  }, []);

  // All engines visible in train mode (show all, including Databricks even without workspace,
  // since training would provision ephemeral ones)
  const allEngines = engines;

  // Engine IDs as string keys for model compatibility check
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
  const compatibleModels = models.filter(m =>
    m.linked_engines.every(le => enabledEngineStringIds.includes(le))
  );

  const handleStartTraining = async () => {
    if (!selectedCollectionId) return;
    setTraining(true);
    setTrainingComplete(false);
    const stages = [
      "Provisioning ephemeral engines...",
      "Running benchmark queries...",
      "Collecting execution metrics...",
      "Training ML model...",
      "Validating model accuracy...",
    ];
    for (const stage of stages) {
      setTrainingStage(stage);
      await new Promise(r => setTimeout(r, 1500));
    }
    // Actually train a model via mock API
    await mockApi.trainModel(enabledEngineStringIds);
    setTraining(false);
    setTrainingStage("");
    setTrainingComplete(true);
  };

  const formatType = (e: typeof engines[0]) =>
    e.engine_type === "duckdb" ? "DuckDB" : "Databricks SQL";

  const formatSpecs = (e: typeof engines[0]) => {
    if (e.engine_type === "duckdb") return `${e.config.memory_gb} GB / ${e.config.cpu_count} CPU`;
    return e.config.cluster_size ?? "";
  };

  const enabledCount = allEngines.filter(e => enabledEngineIds.has(e.id)).length;

  return (
    <div className="flex flex-col h-full text-[12px]">
      {/* Header */}
      <div className="px-3 py-2 border-b border-panel-border flex items-center gap-2">
        <button
          onClick={() => setPanelMode("run")}
          className="text-muted-foreground hover:text-foreground"
          title="Back to Routing"
        >
          <ArrowLeft size={14} />
        </button>
        <Zap size={13} className="text-amber-500" />
        <span className="font-semibold text-foreground">Train New Model</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Step 1: Engine Selection */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">1</span>
            Select Engines
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">
            Choose which engines to include in benchmark and training. All engines are pre-selected.
            {!connectedWorkspace && (
              <span className="italic"> Databricks engines will be provisioned ephemerally.</span>
            )}
          </p>

          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-muted">
                <th className="w-7 px-2 py-1 border-b border-border"></th>
                <th className="text-left px-2 py-1 border-b border-border">Type</th>
                <th className="text-left px-2 py-1 border-b border-border">Specs</th>
              </tr>
            </thead>
            <tbody>
              {allEngines.map(e => (
                <tr key={e.id} className="even:bg-card hover:bg-muted/50">
                  <td className="px-2 py-1 border-b border-border text-center">
                    <input
                      type="checkbox"
                      checked={enabledEngineIds.has(e.id)}
                      onChange={() => toggleEngineEnabled(e.id)}
                      className="accent-primary"
                      disabled={training}
                    />
                  </td>
                  <td className="px-2 py-1 border-b border-border text-foreground font-medium">
                    {formatType(e)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-muted-foreground">
                    {formatSpecs(e)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] text-muted-foreground mt-1">
            {enabledCount} of {allEngines.length} engines selected
          </div>
        </div>

        <div className="border-t border-panel-border" />

        {/* Step 2: Select Query Collection */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">2</span>
            Select Query Collection
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">
            Pick a collection of queries to benchmark. Results are used to train the model.
          </p>

          {collections.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">No collections available. Create one in Queries &amp; Benchmarks.</p>
          ) : (
            <div className="space-y-1">
              {collections.map(c => (
                <label
                  key={c.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded border cursor-pointer ${
                    selectedCollectionId === c.id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-muted"
                  } ${training ? "pointer-events-none opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name="train-collection"
                    checked={selectedCollectionId === c.id}
                    onChange={() => setSelectedCollectionId(c.id)}
                    className="accent-primary shrink-0"
                    disabled={training}
                  />
                  <div className="min-w-0">
                    <div className="text-foreground font-medium">{c.name}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{c.description}</div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-panel-border" />

        {/* Step 3: Existing models for reference */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">3</span>
            Existing Models
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">
            {compatibleModels.length} of {models.length} models are compatible with the selected engines.
          </p>

          {models.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">No models trained yet.</p>
          ) : (
            <div className="space-y-1">
              {models.map(m => {
                const compatible = m.linked_engines.every(le => enabledEngineStringIds.includes(le));
                return (
                  <div
                    key={m.id}
                    className={`px-2 py-1.5 rounded border border-border text-[11px] ${!compatible ? "opacity-40" : ""}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-foreground font-medium">Model #{m.id}</span>
                      {m.is_active && <span className="text-[9px] bg-primary/20 text-primary px-1 rounded">Active</span>}
                      {!compatible && <span className="text-[9px] text-status-warning">Incompatible</span>}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {m.linked_engines.length} engines · R²={m.accuracy_metrics.r_squared.toFixed(2)} · {m.benchmark_count ?? 0} benchmarks
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-panel-border" />

        {/* Action: Start Training */}
        <div className="px-3 py-3">
          {trainingComplete ? (
            <div className="text-center space-y-2">
              <CheckCircle2 size={20} className="text-status-success mx-auto" />
              <p className="text-[11px] text-foreground font-medium">Model trained successfully!</p>
              <p className="text-[10px] text-muted-foreground">The new model is available in Routing &gt; ML Models.</p>
              <button
                onClick={() => setPanelMode("run")}
                className="px-3 py-1.5 border border-primary text-primary rounded-md text-[11px] font-medium w-full hover:bg-primary/5"
              >
                Back to Routing
              </button>
            </div>
          ) : training ? (
            <div className="space-y-2 text-center">
              <div className="animate-spin w-5 h-5 border-2 border-primary border-t-transparent rounded-full mx-auto" />
              <p className="text-[11px] text-muted-foreground">{trainingStage}</p>
            </div>
          ) : (
            <button
              onClick={handleStartTraining}
              disabled={enabledCount < 2 || !selectedCollectionId}
              className="px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[11px] font-medium w-full disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Start Training
            </button>
          )}
          {!training && !trainingComplete && enabledCount < 2 && (
            <p className="text-[10px] text-status-warning mt-1">Select at least 2 engines to train a model.</p>
          )}
          {!training && !trainingComplete && enabledCount >= 2 && !selectedCollectionId && (
            <p className="text-[10px] text-muted-foreground mt-1">Select a query collection above.</p>
          )}
        </div>
      </div>
    </div>
  );
};
