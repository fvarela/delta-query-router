import React, { useState, useEffect, useMemo } from "react";
import { mockApi } from "@/mocks/api";
import { useApp } from "@/contexts/AppContext";
import { isMockMode } from "@/lib/mockMode";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { MOCK_COLLECTIONS_WITH_QUERIES, MOCK_TPCDS_CONFIGURED, MOCK_BENCHMARK_RUN_DETAILS, getRunsForDefinition } from "@/mocks/engineSetupData";
import type { CollectionWithQueries, BenchmarkSummary, BenchmarkDetail, BenchmarkRunDetail } from "@/types";
import { ArrowLeft, Plus, Trash2, X, Database, AlertTriangle, Lock, BarChart3, Clock, ExternalLink } from "lucide-react";

export const CollectionsPanel: React.FC = () => {
  const {
    setEditorSql, setCollectionContext, refreshCollections, activeCollectionId, setActiveCollectionId,
    engines, routingMode, benchmarkEngineIds, benchmarkDefinitions,
  } = useApp();
  const [collections, setCollections] = useState<CollectionWithQueries[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCollection, setActiveCollectionLocal] = useState<CollectionWithQueries | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [selectedQueryId, setSelectedQueryId] = useState<number | null>(null);
  const [deleteCollectionId, setDeleteCollectionId] = useState<number | null>(null);
  const [deleteQueryId, setDeleteQueryId] = useState<number | null>(null);

  // Benchmark state
  const [benchmarks, setBenchmarks] = useState<BenchmarkSummary[]>([]);
  const [benchmarkDetail, setBenchmarkDetail] = useState<BenchmarkDetail | null>(null);
  const [runningBenchmark, setRunningBenchmark] = useState(false);
  const [benchmarkError, setBenchmarkError] = useState<string | null>(null);
  const [runsDialog, setRunsDialog] = useState<{ definitionId: number; engineName: string } | null>(null);

  // TPC-DS dataset configured check
  const tpcdsConfigured = MOCK_TPCDS_CONFIGURED; // TODO: fetch from backend in non-mock mode

  const mock = isMockMode();

  // Per-engine benchmark runs for the active collection
  const collectionEngineRuns = useMemo(() => {
    if (!activeCollection) return [];
    const colDefs = benchmarkDefinitions.filter(d => d.collection_id === activeCollection.id);
    if (colDefs.length === 0) return [];
    return colDefs.map(def => ({
      definitionId: def.id,
      engineId: def.engine_id,
      engineName: def.engine_display_name,
      runCount: def.run_count,
    }));
  }, [activeCollection, benchmarkDefinitions]);

  // Sync activeCollectionId to context for "Add to Collection" button in CenterPanel
  const setActiveCollection = (c: CollectionWithQueries | null) => {
    setActiveCollectionLocal(c);
    setActiveCollectionId(c?.id ?? null);
  };

  useEffect(() => {
    setLoading(true);
    if (mock) {
      // In mock mode, use local mock data directly
      setCollections(MOCK_COLLECTIONS_WITH_QUERIES);
      setLoading(false);
    } else {
      mockApi.getCollections().then(async (cols) => {
        const full = await Promise.all(cols.map(c => mockApi.getCollection(c.id)));
        setCollections(full);
        setLoading(false);
      });
    }
  }, [refreshCollections, mock]);

  // Reload active collection when refreshCollections changes (e.g. after "Add to Collection")
  useEffect(() => {
    if (!activeCollection) return;
    if (mock) {
      const c = MOCK_COLLECTIONS_WITH_QUERIES.find(c => c.id === activeCollection.id);
      if (c) setActiveCollectionLocal(c);
    } else {
      mockApi.getCollection(activeCollection.id).then(c => setActiveCollectionLocal(c));
    }
  }, [refreshCollections]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-open collection when activeCollectionId is set from center panel (benchmark collection selector)
  useEffect(() => {
    if (activeCollectionId === null) return;
    // Don't re-open if already viewing this collection
    if (activeCollection?.id === activeCollectionId) return;
    // Find collection in loaded list and open it
    const col = collections.find(c => c.id === activeCollectionId);
    if (col) {
      setActiveCollectionLocal(col);
      setSelectedQueryId(null);
      if (!mock) {
        mockApi.getBenchmarks(activeCollectionId).then(b => setBenchmarks(b));
      } else {
        setBenchmarks([]);
      }
      setBenchmarkDetail(null);
    }
  }, [activeCollectionId, collections]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCollection = async (id: number) => {
    let c: CollectionWithQueries;
    if (mock) {
      c = MOCK_COLLECTIONS_WITH_QUERIES.find(col => col.id === id)!;
    } else {
      c = await mockApi.getCollection(id);
    }
    setActiveCollection(c);
    setSelectedQueryId(null);
    if (!mock) {
      const b = await mockApi.getBenchmarks(id);
      setBenchmarks(b);
    } else {
      setBenchmarks([]);
    }
    setBenchmarkDetail(null);
  };

  const handleCreate = async () => {
    if (!newName) return;
    if (mock) {
      const newId = Math.max(...collections.map(c => c.id)) + 1;
      const newCol: CollectionWithQueries = {
        id: newId, name: newName, description: newDesc,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        tag: "user", queries: [],
      };
      setCollections(prev => [...prev, newCol]);
    } else {
      const created = await mockApi.createCollection(newName, newDesc);
      const full = await mockApi.getCollection(created.id);
      setCollections(prev => [...prev, full]);
    }
    setShowCreate(false);
    setNewName("");
    setNewDesc("");
  };

  const handleDeleteCollection = async () => {
    if (deleteCollectionId === null) return;
    if (!mock) {
      await mockApi.deleteCollection(deleteCollectionId);
    }
    setCollections(prev => prev.filter(c => c.id !== deleteCollectionId));
    if (activeCollection?.id === deleteCollectionId) setActiveCollection(null);
    setDeleteCollectionId(null);
  };

  const handleSelectQuery = (qId: number, qText: string, seq: number) => {
    setSelectedQueryId(qId);
    setEditorSql(qText);
    setCollectionContext({
      collectionName: activeCollection!.name,
      queryLabel: `Q${seq}`,
      originalSql: qText,
    });
  };

  const handleDeleteQuery = async () => {
    if (!activeCollection || deleteQueryId === null) return;
    if (!mock) {
      await mockApi.deleteQuery(activeCollection.id, deleteQueryId);
      const c = await mockApi.getCollection(activeCollection.id);
      setActiveCollection(c);
    }
    setDeleteQueryId(null);
  };

  const handleRunBenchmark = async () => {
    if (!activeCollection) return;
    // In benchmark mode, use engines selected in the right panel's BenchmarkingView
    const engineIds = [...benchmarkEngineIds];
    if (engineIds.length === 0) {
      setBenchmarkError("No engines selected. Switch to Benchmarking mode and select engines in the right panel.");
      return;
    }
    setRunningBenchmark(true);
    setBenchmarkError(null);
    try {
      await mockApi.createBenchmark(activeCollection.id, engineIds);
      const b = await mockApi.getBenchmarks(activeCollection.id);
      setBenchmarks(b);
    } catch (e: any) {
      setBenchmarkError(e?.message || "Benchmark failed");
    } finally {
      setRunningBenchmark(false);
    }
  };

  const openBenchmarkDetail = async (id: number) => {
    const d = await mockApi.getBenchmark(id);
    setBenchmarkDetail(d);
  };

  if (loading) return <div className="p-3"><LoadingSpinner /></div>;

  const isTpcds = (c: CollectionWithQueries) => c.tag === "tpcds";
  const tpcdsCollections = collections.filter(isTpcds);
  const userCollections = collections.filter(c => !isTpcds(c));

  // Benchmark Detail View
  if (benchmarkDetail) {
    const engineNames = [...new Set(benchmarkDetail.results.map(r => r.engine_display_name))];
    const queryIds = [...new Set(benchmarkDetail.results.map(r => r.query_id))];

    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-2 border-b border-panel-border flex items-center gap-2">
          <button onClick={() => setBenchmarkDetail(null)}><ArrowLeft size={14} /></button>
          <span className="font-semibold text-foreground">Benchmark #{benchmarkDetail.id}</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <div className="text-[11px] text-muted-foreground">
            <p>Date: {new Date(benchmarkDetail.created_at).toLocaleString()}</p>
            <p>Engines: {benchmarkDetail.engine_count} | Queries: {queryIds.length}</p>
          </div>

          <div>
            <h4 className="font-semibold mb-1 text-foreground">Warm-up Times</h4>
            <table className="w-full border border-border text-[11px]">
              <thead><tr className="bg-muted"><th className="text-left px-2 py-1 border-b border-border">Engine</th><th className="text-right px-2 py-1 border-b border-border">Cold Start (ms)</th></tr></thead>
              <tbody>
                {benchmarkDetail.warmups.map(w => (
                  <tr key={w.engine_id} className="even:bg-card">
                    <td className="px-2 py-1 border-b border-border text-foreground">{w.engine_display_name}</td>
                    <td className="px-2 py-1 border-b border-border text-right text-foreground">{w.cold_start_time_ms != null ? w.cold_start_time_ms.toLocaleString() : <span className="text-status-error">failed</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h4 className="font-semibold mb-1 text-foreground">Results (ms)</h4>
            <div className="overflow-x-auto">
              <table className="border-collapse border border-border text-[11px]" style={{ minWidth: "100%" }}>
                <thead>
                  <tr className="bg-muted">
                    <th className="text-left px-2 py-1 border-b border-r border-border sticky left-0 bg-muted z-10 min-w-[100px]">Engine</th>
                    {queryIds.map((_qId, i) => (
                      <th key={i} className="text-right px-2 py-1 border-b border-border whitespace-nowrap">Q{i + 1}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {engineNames.map((engine, eIdx) => (
                    <tr key={engine} className={eIdx % 2 ? "bg-card" : ""}>
                      <td className="px-2 py-1 border-b border-r border-border font-medium text-foreground sticky left-0 z-10 whitespace-nowrap"
                          style={{ backgroundColor: eIdx % 2 ? "var(--card)" : "var(--background)" }}>
                        {engine}
                      </td>
                      {queryIds.map((qId, qIdx) => {
                        const r = benchmarkDetail.results.find(res => res.query_id === qId && res.engine_display_name === engine);
                        const v = r?.execution_time_ms;
                        if (v == null) {
                          return (
                            <td key={qIdx} className="px-2 py-1 border-b border-border text-right text-status-error" title={r?.error_message ?? "no data"}>
                              —
                            </td>
                          );
                        }
                        const colTimes = engineNames.map(e => benchmarkDetail.results.find(res => res.query_id === qId && res.engine_display_name === e)?.execution_time_ms).filter((t): t is number => t != null);
                        const min = Math.min(...colTimes);
                        const max = Math.max(...colTimes);
                        const colorClass = v === min ? "text-status-success font-semibold" : v === max ? "text-status-error" : "text-foreground";
                        return (
                          <td key={qIdx} className={`px-2 py-1 border-b border-border text-right ${colorClass}`}>
                            {v.toLocaleString()}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </div>
    );
  }

  // Collection Detail View
  if (activeCollection) {
    const readOnly = isTpcds(activeCollection);
    const tpcdsNotConfigured = readOnly && !tpcdsConfigured;

    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-2 border-b border-panel-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button onClick={() => { setActiveCollection(null); setCollectionContext(null); }}><ArrowLeft size={14} /></button>
            <span className="font-semibold text-foreground">{activeCollection.name}</span>
            {readOnly && (
              <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 text-[9px] font-medium flex items-center gap-0.5">
                <Lock size={8} /> TPC-DS
              </span>
            )}
          </div>
          {!readOnly && (
            <button onClick={() => setDeleteCollectionId(activeCollection.id)} className="text-muted-foreground hover:text-status-error">
              <Trash2 size={13} />
            </button>
          )}
        </div>
        <p className="px-3 py-1 text-[11px] text-muted-foreground">{activeCollection.description}</p>

        {/* TPC-DS dataset not configured warning */}
        {tpcdsNotConfigured && (
          <div className="mx-3 mt-1 mb-1 p-2 rounded border border-amber-200 bg-amber-50 flex items-start gap-2">
            <AlertTriangle size={13} className="text-amber-500 shrink-0 mt-0.5" />
            <div className="text-[11px]">
              <span className="font-medium text-amber-700">TPC-DS dataset not configured.</span>
              <span className="text-amber-600"> Configure the TPC-DS dataset to run benchmarks with this collection.</span>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <div className="px-3 space-y-1 py-2">
            {activeCollection.queries.map(q => (
              <div
                key={q.id}
                className={`flex items-center justify-between px-2 py-1.5 rounded cursor-pointer border ${
                  selectedQueryId === q.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                }`}
                onClick={() => handleSelectQuery(q.id, q.query_text, q.sequence_number)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-medium text-muted-foreground shrink-0">Q{q.sequence_number}</span>
                  <span className="truncate font-mono text-[11px] text-foreground">{q.query_text.slice(0, 60)}</span>
                </div>
                {!readOnly && (
                  <button onClick={e => { e.stopPropagation(); setDeleteQueryId(q.id); }} className="text-muted-foreground hover:text-status-error shrink-0 ml-1">
                    <X size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* Benchmark section — only if not TPC-DS without dataset */}
          {!tpcdsNotConfigured && (
            <div className="px-3 py-2 border-t border-panel-border">
              {runningBenchmark ? (
                <div className="space-y-2">
                  <LoadingSpinner />
                  <p className="text-[11px] text-muted-foreground">Running benchmark...</p>
                </div>
              ) : (
                <>
                  {(() => {
                    const isBenchmarkMode = routingMode === "benchmark";
                    const hasEnginesSelected = benchmarkEngineIds.size > 0;
                    const isDisabled = !isBenchmarkMode || !hasEnginesSelected;
                    return (
                      <>
                        <button
                          onClick={handleRunBenchmark}
                          disabled={isDisabled}
                          className={`px-3 py-1.5 rounded-md text-[11px] font-medium w-full ${
                            isDisabled
                              ? "bg-muted text-muted-foreground cursor-not-allowed"
                              : "bg-amber-600 text-white hover:bg-amber-700"
                          }`}
                        >
                          Run Benchmark
                        </button>
                        {!isBenchmarkMode && (
                          <p className="text-[10px] text-muted-foreground mt-1">
                            Switch to Benchmarking mode in the right panel to run benchmarks.
                          </p>
                        )}
                        {isBenchmarkMode && !hasEnginesSelected && (
                          <p className="text-[10px] text-amber-600 mt-1">
                            Select engines in the right panel to enable.
                          </p>
                        )}
                      </>
                    );
                  })()}
                  {benchmarkError && (
                    <p className="text-[11px] text-status-error mt-1">{benchmarkError}</p>
                  )}
                </>
              )}
            </div>
          )}

          {/* Runs by engine */}
          {collectionEngineRuns.length > 0 && (
            <div className="px-3 py-2 border-t border-panel-border">
              <div className="flex items-center gap-1.5 mb-1.5">
                <BarChart3 size={11} className="text-muted-foreground" />
                <span className="text-[11px] font-semibold text-foreground">Runs by Engine</span>
              </div>
              {collectionEngineRuns.map(({ definitionId, engineName, runCount }) => (
                <div
                  key={definitionId}
                  className="flex items-center justify-between px-2 py-1.5 hover:bg-muted/30 rounded text-[11px]"
                >
                  <span className="text-foreground font-medium truncate min-w-0">{engineName}</span>
                  {runCount > 0 ? (
                    <button
                      onClick={() => setRunsDialog({ definitionId, engineName })}
                      className="text-[10px] text-primary hover:underline shrink-0 ml-2"
                    >
                      {runCount} run{runCount !== 1 ? "s" : ""}
                    </button>
                  ) : (
                    <span className="text-[10px] text-muted-foreground shrink-0 ml-2">No runs</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {benchmarks.length > 0 && (
            <div className="px-3 py-2 border-t border-panel-border">
              <h4 className="font-semibold mb-1 text-foreground">Benchmark History</h4>
              {benchmarks.map(b => (
                <button
                  key={b.id}
                  onClick={() => openBenchmarkDetail(b.id)}
                  className="flex items-center justify-between w-full px-2 py-1 hover:bg-muted rounded text-[11px]"
                >
                  <span className="text-foreground">{new Date(b.created_at).toLocaleDateString()}</span>
                  <div className="flex items-center gap-2">
                    <StatusBadge variant={b.status === "complete" ? "success" : b.status === "failed" ? "error" : "warning"}>{b.status}</StatusBadge>
                    <span className="text-muted-foreground">{b.engine_count} eng</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {!readOnly && (
          <>
            <ConfirmDialog open={deleteCollectionId !== null} title="Delete Collection" description={`Delete collection '${activeCollection.name}' and all its queries? This cannot be undone.`} onConfirm={handleDeleteCollection} onCancel={() => setDeleteCollectionId(null)} destructive />
            <ConfirmDialog open={deleteQueryId !== null} title="Remove Query" description="Remove this query from the collection?" onConfirm={handleDeleteQuery} onCancel={() => setDeleteQueryId(null)} destructive />
          </>
        )}

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
  }

  // Collection List View
  return (
    <div className="flex flex-col h-full text-[12px]">
      <div className="px-3 py-2 border-b border-panel-border flex items-center justify-between">
        <span className="font-semibold text-foreground">Collections</span>
        <button onClick={() => setShowCreate(true)} className="text-primary hover:text-primary/80" title="New collection"><Plus size={14} /></button>
      </div>

      <div className="px-3 py-2 text-[10px] text-muted-foreground border-b border-border">
        Group queries into collections, then run benchmarks to measure engine performance.
      </div>

      {showCreate && (
        <div className="px-3 py-2 border-b border-border space-y-2">
          <input placeholder="Collection name" value={newName} onChange={e => setNewName(e.target.value)} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
          <input placeholder="Description (optional)" value={newDesc} onChange={e => setNewDesc(e.target.value)} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
          <div className="flex gap-2">
            <button onClick={handleCreate} className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px]">Create</button>
            <button onClick={() => setShowCreate(false)} className="px-3 py-1 border border-border rounded text-[11px]">Cancel</button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* TPC-DS Collections */}
        {tpcdsCollections.length > 0 && (
          <>
            <div className="px-3 py-1.5 flex items-center gap-1.5 bg-muted/30 border-b border-border">
              <Database size={11} className="text-amber-500" />
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">TPC-DS Benchmarks</span>
              {!tpcdsConfigured && (
                <span className="ml-auto flex items-center gap-0.5 text-[9px] text-amber-600">
                  <AlertTriangle size={9} /> Not configured
                </span>
              )}
            </div>
            {tpcdsCollections.map(c => (
              <button
                key={c.id}
                onClick={() => openCollection(c.id)}
                className={`flex flex-col w-full px-3 py-2 hover:bg-muted text-left border-b border-border gap-0.5 ${!tpcdsConfigured ? "opacity-60" : ""}`}
              >
                <div className="flex items-center justify-between w-full">
                  <div className="flex items-center gap-1.5">
                    <Lock size={9} className="text-amber-500" />
                    <span className="text-foreground font-medium">{c.name}</span>
                  </div>
                  <span className="text-[10px] text-muted-foreground">{c.queries.length} queries</span>
                </div>
                {c.description && (
                  <span className="text-[10px] text-muted-foreground truncate pl-[18px]">{c.description}</span>
                )}
              </button>
            ))}
          </>
        )}

        {/* User Collections */}
        {userCollections.length > 0 && (
          <>
            <div className="px-3 py-1.5 flex items-center gap-1.5 bg-muted/30 border-b border-border">
              <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">User Collections</span>
            </div>
            {userCollections.map(c => (
              <button
                key={c.id}
                onClick={() => openCollection(c.id)}
                className="flex flex-col w-full px-3 py-2 hover:bg-muted text-left border-b border-border gap-0.5"
              >
                <div className="flex items-center justify-between w-full">
                  <span className="text-foreground font-medium">{c.name}</span>
                  <span className="text-[10px] text-muted-foreground">{c.queries.length} queries</span>
                </div>
                {c.description && (
                  <span className="text-[10px] text-muted-foreground truncate">{c.description}</span>
                )}
              </button>
            ))}
          </>
        )}

        {tpcdsCollections.length === 0 && userCollections.length === 0 && (
          <div className="px-3 py-6 text-center text-muted-foreground text-[11px]">
            No collections yet. Create one or configure TPC-DS datasets.
          </div>
        )}
      </div>
    </div>
  );
};

// ---- Helpers ----

const latencyColor = (ms: number) => {
  if (ms < 100) return "text-status-success";
  if (ms < 500) return "text-status-warning";
  return "text-status-error";
};

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
