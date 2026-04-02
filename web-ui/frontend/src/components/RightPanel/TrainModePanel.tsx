import React, { useState, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { ArrowLeft, Zap, CheckCircle2, Minus, Plus, History } from "lucide-react";
import type { Collection, BenchmarkSummary } from "@/types";

interface CollectionSelection {
  id: number;
  name: string;
  runs: number;
}

export const TrainModePanel: React.FC = () => {
  const {
    setPanelMode, engines, enabledEngineIds, toggleEngineEnabled,
    models, connectedWorkspace,
  } = useApp();

  const [collections, setCollections] = useState<Collection[]>([]);
  const [selectedCollections, setSelectedCollections] = useState<CollectionSelection[]>([]);
  const [allBenchmarks, setAllBenchmarks] = useState<(BenchmarkSummary & { collectionName?: string })[]>([]);
  const [selectedBenchmarkIds, setSelectedBenchmarkIds] = useState<Set<number>>(new Set());
  const [training, setTraining] = useState(false);
  const [trainingStage, setTrainingStage] = useState("");
  const [trainingComplete, setTrainingComplete] = useState(false);

  useEffect(() => {
    mockApi.getCollections().then(setCollections);
    mockApi.getBenchmarks().then(async (bms) => {
      // Enrich with collection names
      const cols = await mockApi.getCollections();
      const colMap = new Map(cols.map(c => [c.id, c.name]));
      setAllBenchmarks(bms.filter(b => b.status === "complete").map(b => ({
        ...b,
        collectionName: colMap.get(b.collection_id) ?? `Collection #${b.collection_id}`,
      })));
    });
  }, []);

  // All engines visible in train mode
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

  // Collection selection handlers
  const toggleCollection = (col: Collection) => {
    setSelectedCollections(prev => {
      const exists = prev.find(s => s.id === col.id);
      if (exists) return prev.filter(s => s.id !== col.id);
      return [...prev, { id: col.id, name: col.name, runs: 1 }];
    });
  };

  const setCollectionRuns = (id: number, runs: number) => {
    setSelectedCollections(prev =>
      prev.map(s => s.id === id ? { ...s, runs: Math.max(1, Math.min(10, runs)) } : s)
    );
  };

  // Benchmark selection handlers
  const toggleBenchmark = (id: number) => {
    setSelectedBenchmarkIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Training data summary
  const newRunCount = selectedCollections.reduce((sum, c) => sum + c.runs, 0);
  const pastBenchmarkCount = selectedBenchmarkIds.size;
  const totalDataSources = newRunCount + pastBenchmarkCount;

  const handleStartTraining = async () => {
    if (totalDataSources === 0) return;
    setTraining(true);
    setTrainingComplete(false);
    const stages = [
      "Provisioning ephemeral engines...",
      ...(newRunCount > 0 ? [`Running ${newRunCount} benchmark run${newRunCount > 1 ? "s" : ""} across ${selectedCollections.length} collection${selectedCollections.length > 1 ? "s" : ""}...`] : []),
      ...(pastBenchmarkCount > 0 ? [`Loading ${pastBenchmarkCount} historical benchmark${pastBenchmarkCount > 1 ? "s" : ""}...`] : []),
      "Collecting execution metrics...",
      "Training ML model...",
      "Validating model accuracy...",
    ];
    for (const stage of stages) {
      setTrainingStage(stage);
      await new Promise(r => setTimeout(r, 1500));
    }
    await mockApi.trainModel(enabledEngineStringIds, {
      collections: selectedCollections.map(c => ({ id: c.id, runs: c.runs })),
      benchmarkIds: [...selectedBenchmarkIds],
    });
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
            Choose which engines to include in benchmark and training.
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

        {/* Step 2: Select Query Collections (multi-select with run count) */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">2</span>
            Select Query Collections
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">
            Pick collections to benchmark for training data. Configure how many runs per collection. More runs = more training data.
          </p>

          {collections.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">No collections available. Create one in Queries &amp; Benchmarks.</p>
          ) : (
            <div className="space-y-1">
              {collections.map(c => {
                const sel = selectedCollections.find(s => s.id === c.id);
                const isSelected = !!sel;
                return (
                  <div
                    key={c.id}
                    className={`rounded border ${
                      isSelected ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                    } ${training ? "pointer-events-none opacity-60" : ""}`}
                  >
                    <label className="flex items-center gap-2 px-2 py-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleCollection(c)}
                        className="accent-primary shrink-0"
                        disabled={training}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-foreground font-medium">{c.name}</div>
                        <div className="text-[10px] text-muted-foreground truncate">{c.description}</div>
                      </div>
                    </label>
                    {isSelected && (
                      <div className="px-2 pb-1.5 ml-6 flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground">Runs:</span>
                        <button
                          onClick={() => setCollectionRuns(c.id, (sel?.runs ?? 1) - 1)}
                          disabled={training || (sel?.runs ?? 1) <= 1}
                          className="w-5 h-5 flex items-center justify-center rounded border border-border text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30"
                        >
                          <Minus size={10} />
                        </button>
                        <span className="text-foreground font-medium w-4 text-center">{sel?.runs ?? 1}</span>
                        <button
                          onClick={() => setCollectionRuns(c.id, (sel?.runs ?? 1) + 1)}
                          disabled={training || (sel?.runs ?? 1) >= 10}
                          className="w-5 h-5 flex items-center justify-center rounded border border-border text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30"
                        >
                          <Plus size={10} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {selectedCollections.length > 0 && (
            <div className="text-[10px] text-muted-foreground mt-1.5">
              {selectedCollections.length} collection{selectedCollections.length > 1 ? "s" : ""} selected, {newRunCount} total run{newRunCount > 1 ? "s" : ""}
            </div>
          )}
        </div>

        <div className="border-t border-panel-border" />

        {/* Step 3: Include Past Benchmarks */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">3</span>
            Include Past Benchmarks
          </div>
          <p className="text-[10px] text-muted-foreground mb-2">
            Optionally include historical benchmark results in the training data. Reuse known-good runs for better model accuracy.
          </p>

          {allBenchmarks.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">No completed benchmarks available.</p>
          ) : (
            <div className="space-y-1">
              {allBenchmarks.map(b => {
                const isSelected = selectedBenchmarkIds.has(b.id);
                return (
                  <label
                    key={b.id}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded border cursor-pointer ${
                      isSelected ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                    } ${training ? "pointer-events-none opacity-60" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleBenchmark(b.id)}
                      className="accent-primary shrink-0"
                      disabled={training}
                    />
                    <History size={11} className="text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-foreground font-medium">
                        {b.collectionName}
                        <span className="text-muted-foreground font-normal"> — Run #{b.id}</span>
                      </div>
                      <div className="text-[10px] text-muted-foreground">
                        {new Date(b.created_at).toLocaleDateString()} · {b.engine_count} engines
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
          {selectedBenchmarkIds.size > 0 && (
            <div className="text-[10px] text-muted-foreground mt-1.5">
              {pastBenchmarkCount} historical benchmark{pastBenchmarkCount > 1 ? "s" : ""} selected
            </div>
          )}
        </div>

        <div className="border-t border-panel-border" />

        {/* Step 4: Existing models for reference */}
        <div className="px-3 py-2">
          <div className="font-semibold text-foreground mb-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground bg-muted rounded-full w-4 h-4 flex items-center justify-center shrink-0">4</span>
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
                      {m.linked_engines.length} engines · R²={m.latency_model.r_squared.toFixed(2)} · {m.benchmark_count ?? 0} benchmarks
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-panel-border" />

        {/* Action: Review & Start Training */}
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
            <>
              {/* Training data summary */}
              {totalDataSources > 0 && (
                <div className="mb-2 px-2 py-1.5 bg-muted rounded text-[10px] text-muted-foreground">
                  <span className="font-medium text-foreground">Training data:</span>{" "}
                  {newRunCount > 0 && <span>{newRunCount} new benchmark run{newRunCount > 1 ? "s" : ""}</span>}
                  {newRunCount > 0 && pastBenchmarkCount > 0 && <span> + </span>}
                  {pastBenchmarkCount > 0 && <span>{pastBenchmarkCount} historical benchmark{pastBenchmarkCount > 1 ? "s" : ""}</span>}
                </div>
              )}
              <button
                onClick={handleStartTraining}
                disabled={enabledCount < 2 || totalDataSources === 0}
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[11px] font-medium w-full disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Start Training
              </button>
            </>
          )}
          {!training && !trainingComplete && enabledCount < 2 && (
            <p className="text-[10px] text-status-warning mt-1">Select at least 2 engines to train a model.</p>
          )}
          {!training && !trainingComplete && enabledCount >= 2 && totalDataSources === 0 && (
            <p className="text-[10px] text-muted-foreground mt-1">Select collections for new benchmark runs and/or include past benchmarks above.</p>
          )}
        </div>
      </div>
    </div>
  );
};
