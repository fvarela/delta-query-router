import React, { useState, useMemo } from "react";
import { useApp } from "@/contexts/AppContext";
import { MOCK_BENCHMARK_RUN_DETAILS, getRunsForDefinition } from "@/mocks/engineSetupData";
import type { BenchmarkRunDetail, EngineCatalogEntry } from "@/types";
import { BarChart3, Info, X, Clock, ExternalLink, ArrowLeft } from "lucide-react";

// ---- Helpers ----

const latencyColor = (ms: number) => {
  if (ms < 100) return "text-status-success";
  if (ms < 500) return "text-status-warning";
  return "text-status-error";
};

// ---- Main Component: Runs-only Layout ----

export const EngineSetupView: React.FC = () => {
  const {
    engines, enabledEngineIds, benchmarkDefinitions,
    selectedBenchmarkCollectionId, setSelectedBenchmarkCollectionId,
    selectedBenchmarkEngineIds, toggleBenchmarkEngineId,
  } = useApp();

  // Local state
  const [runsDialog, setRunsDialog] = useState<{ definitionId: number; engineName: string } | null>(null);

  // Available collections for the benchmark selector
  const availableCollections = useMemo(() => {
    const collectionIds = [...new Set(benchmarkDefinitions.map(d => d.collection_id))];
    return collectionIds.map(cid => {
      const colDefs = benchmarkDefinitions.filter(d => d.collection_id === cid);
      return { id: cid, name: colDefs[0]?.collection_name ?? `Collection ${cid}` };
    });
  }, [benchmarkDefinitions]);

  // Benchmark data for the selected collection only
  const selectedCollectionBenchmarks = useMemo(() => {
    if (selectedBenchmarkCollectionId === null) return null;

    const colDefs = benchmarkDefinitions.filter(d => d.collection_id === selectedBenchmarkCollectionId);
    const collectionName = colDefs[0]?.collection_name ?? `Collection ${selectedBenchmarkCollectionId}`;

    // Show all enabled engines
    const selectedEngs = engines.filter(e => enabledEngineIds.has(e.id));

    const engineEntries = selectedEngs.map(eng => {
      const existing = colDefs.find(d => d.engine_id === eng.id);
      return {
        engine: eng,
        definition: existing ?? null,
        key: `${selectedBenchmarkCollectionId}-${eng.id}`,
      };
    });

    return { collectionId: selectedBenchmarkCollectionId, collectionName, engineEntries };
  }, [benchmarkDefinitions, engines, enabledEngineIds, selectedBenchmarkCollectionId]);

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* ---- Runs (Collection selector + engine rows) ---- */}
      <div className="shrink-0">
        <SectionHeader icon={BarChart3} title="Runs" subtitle="By collection and engine" />

        {/* Collection selector */}
        <div className="px-3 py-2 border-b border-border bg-card/50">
          <label className="text-[10px] text-muted-foreground block mb-1">Collection</label>
          <select
            value={selectedBenchmarkCollectionId ?? ""}
            onChange={e => {
              const val = e.target.value;
              setSelectedBenchmarkCollectionId(val ? Number(val) : null);
            }}
            className="w-full px-2 py-1.5 border border-border rounded text-[11px] bg-background text-foreground"
          >
            <option value="">Select a collection...</option>
            {availableCollections.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {selectedBenchmarkCollectionId === null ? (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
            <BarChart3 size={20} className="mb-2 opacity-50" />
            <p className="text-[11px]">Select a collection above to see benchmark data.</p>
            <p className="text-[10px] mt-0.5">Run benchmarks from the Collections panel on the left.</p>
          </div>
        ) : selectedCollectionBenchmarks ? (
          <div>
            {/* Engine rows with checkboxes for benchmark engine selection */}
            {selectedCollectionBenchmarks.engineEntries.map(({ engine, definition, key }) => {
              const isEngineChecked = selectedBenchmarkEngineIds.has(engine.id);
              const hasRuns = definition && definition.run_count > 0;

              return (
                <div key={key} className="border-t border-border/50">
                  <div className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted/20 transition-colors">
                    {/* Engine checkbox for "Run Benchmark" enablement */}
                    <input
                      type="checkbox"
                      checked={isEngineChecked}
                      onChange={() => toggleBenchmarkEngineId(engine.id)}
                      className="accent-primary shrink-0"
                      title="Select engine for benchmark run"
                    />

                    {/* Engine name */}
                    <span className="text-[11px] font-medium text-foreground flex-1 min-w-0 truncate">
                      {engine.display_name}
                    </span>

                    {/* Run count — clickable link when runs exist */}
                    {hasRuns ? (
                      <button
                        onClick={() => setRunsDialog({ definitionId: definition.id, engineName: engine.display_name })}
                        className="text-[10px] text-primary hover:underline shrink-0"
                      >
                        {definition.run_count} run{definition.run_count !== 1 ? "s" : ""}
                      </button>
                    ) : (
                      <span className="text-[10px] text-muted-foreground shrink-0">No runs</span>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Hint about running benchmarks */}
            {selectedBenchmarkEngineIds.size > 0 && (
              <div className="px-3 py-2 bg-primary/5 border-t border-border flex items-center gap-2">
                <Info size={11} className="text-primary shrink-0" />
                <span className="text-[10px] text-primary">
                  {selectedBenchmarkEngineIds.size} engine{selectedBenchmarkEngineIds.size !== 1 ? "s" : ""} selected — use "Run Benchmark" in the Collections panel to start.
                </span>
              </div>
            )}
          </div>
        ) : null}
      </div>

      {/* ---- Section 3: ML Models ---- REMOVED in Round 24 */}

      {/* Bottom spacer for scroll comfort */}
      <div className="h-8 shrink-0" />

      {/* Runs dialog */}
      {runsDialog && (
        <RunsDialog
          definitionId={runsDialog.definitionId}
          engineName={runsDialog.engineName}
          onClose={() => setRunsDialog(null)}
        />
      )}
    </div>
  );
};

// ---- Section Header ----

const SectionHeader: React.FC<{
  icon: React.FC<{ size?: number; className?: string }>;
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}> = ({ icon: Icon, title, subtitle, children }) => (
  <div className="flex items-center gap-2 px-3 py-2 bg-card border-b border-border shrink-0">
    <Icon size={13} className="text-muted-foreground" />
    <span className="text-[12px] font-semibold text-foreground">{title}</span>
    {subtitle && <span className="text-[10px] text-muted-foreground">— {subtitle}</span>}
    <div className="ml-auto flex items-center gap-2">{children}</div>
  </div>
);

// ---- Runs Dialog (run list + drill-down to run detail) ----

const RunsDialog: React.FC<{
  definitionId: number;
  engineName: string;
  onClose: () => void;
}> = ({ definitionId, engineName, onClose }) => {
  const runs = useMemo(() => getRunsForDefinition(definitionId), [definitionId]);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRunDetail | null>(null);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-background border border-border rounded-lg shadow-xl max-w-lg w-full mx-4 max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            {selectedRun && (
              <button
                onClick={() => setSelectedRun(null)}
                className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-muted/50"
                title="Back to run list"
              >
                <ArrowLeft size={14} />
              </button>
            )}
            <div>
              <h3 className="text-[13px] font-semibold text-foreground">
                {selectedRun
                  ? `Run #${selectedRun.id} — ${new Date(selectedRun.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
                  : `${engineName} — ${runs.length} run${runs.length !== 1 ? "s" : ""}`}
              </h3>
              <p className="text-[10px] text-muted-foreground mt-0.5">
                {selectedRun
                  ? `${selectedRun.results.length} queries`
                  : "Click Details to view per-query results"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted/50">
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1">
          {selectedRun ? (
            <RunDetailView runDetail={selectedRun} />
          ) : (
            <RunListView runs={runs} onViewDetail={setSelectedRun} />
          )}
        </div>
      </div>
    </div>
  );
};

// ---- Run List View (inside dialog) ----

const RunListView: React.FC<{
  runs: BenchmarkRunDetail[];
  onViewDetail: (run: BenchmarkRunDetail) => void;
}> = ({ runs, onViewDetail }) => {
  if (runs.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-[11px] text-muted-foreground">
        No run data available. Run a benchmark to see results.
      </div>
    );
  }

  return (
    <div>
      {runs.map((run, idx) => {
        const totalMs = run.results.reduce((s, r) => s + (r.execution_time_ms ?? 0), 0);
        const queryCount = run.results.length;
        const date = new Date(run.created_at);
        const dateStr = date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
        const timeStr = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
        const warmup = run.warmups[0];

        return (
          <div
            key={run.id}
            className={`flex items-center gap-3 px-4 py-2.5 text-[11px] ${
              idx > 0 ? "border-t border-border/50" : ""
            } hover:bg-muted/30 transition-colors`}
          >
            <Clock size={11} className="text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-foreground font-medium">{dateStr}</span>
                <span className="text-muted-foreground">{timeStr}</span>
              </div>
              <div className="flex items-center gap-3 mt-0.5 text-[10px] text-muted-foreground">
                <span>Total: <span className="font-mono text-foreground">{totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}</span></span>
                <span>{queryCount} quer{queryCount !== 1 ? "ies" : "y"}</span>
                {warmup && <span>Cold start: <span className={`font-mono ${latencyColor(warmup.cold_start_time_ms ?? 0)}`}>{warmup.cold_start_time_ms}ms</span></span>}
              </div>
            </div>
            <button
              onClick={() => onViewDetail(run)}
              className="flex items-center gap-1 text-[10px] text-primary hover:underline shrink-0"
            >
              Details <ExternalLink size={9} />
            </button>
          </div>
        );
      })}
    </div>
  );
};

// ---- Run Detail View (inside dialog) ----

const RunDetailView: React.FC<{ runDetail: BenchmarkRunDetail }> = ({ runDetail }) => {
  const warmup = runDetail.warmups[0];
  const totalMs = runDetail.results.reduce((s, r) => s + (r.execution_time_ms ?? 0), 0);
  const avgMs = Math.round(totalMs / runDetail.results.length);
  const minMs = Math.min(...runDetail.results.map(r => r.execution_time_ms ?? Infinity));
  const maxMs = Math.max(...runDetail.results.map(r => r.execution_time_ms ?? 0));

  return (
    <div className="px-4 py-3">
      {/* Summary stats */}
      <div className="flex items-center gap-4 mb-3 text-[11px]">
        {warmup && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Cold start:</span>
            <span className={`font-mono ${latencyColor(warmup.cold_start_time_ms ?? 0)}`}>
              {warmup.cold_start_time_ms}ms
            </span>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Total:</span>
          <span className="font-mono text-foreground">
            {totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Avg:</span>
          <span className="font-mono text-foreground">{avgMs}ms</span>
        </div>
      </div>

      {/* Per-query results table */}
      <div className="border border-border rounded overflow-hidden">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="bg-muted">
              <th className="text-left px-2 py-1.5 border-b border-border font-semibold">Query</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Time (ms)</th>
              <th className="text-left px-3 py-1.5 border-b border-border font-semibold w-[40%]">Distribution</th>
            </tr>
          </thead>
          <tbody>
            {runDetail.results.map((r, i) => {
              const pct = maxMs > 0 ? ((r.execution_time_ms ?? 0) / maxMs) * 100 : 0;

              return (
                <tr key={i} className="even:bg-card/50">
                  <td className="px-2 py-1 border-b border-border font-mono text-foreground">Q{r.query_id}</td>
                  <td className={`px-2 py-1 border-b border-border text-right font-mono ${latencyColor(r.execution_time_ms ?? 0)}`}>
                    {r.execution_time_ms ?? "ERR"}
                  </td>
                  <td className="px-3 py-1 border-b border-border">
                    <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${(r.execution_time_ms ?? 0) < 100 ? "bg-status-success" : (r.execution_time_ms ?? 0) < 300 ? "bg-status-warning" : "bg-status-error"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Bottom stats */}
      <div className="flex items-center gap-4 mt-3 text-[10px] text-muted-foreground">
        <span>Min: <span className="font-mono text-foreground">{minMs}ms</span></span>
        <span>Max: <span className="font-mono text-foreground">{maxMs}ms</span></span>
        <span>Avg: <span className="font-mono text-foreground">{avgMs}ms</span></span>
        <span>Total: <span className="font-mono text-foreground">{totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}</span></span>
      </div>
    </div>
  );
};
