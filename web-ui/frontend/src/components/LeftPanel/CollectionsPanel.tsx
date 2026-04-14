import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { isMockMode } from "@/lib/mockMode";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { MOCK_COLLECTIONS_WITH_QUERIES, MOCK_TPCDS_CONFIGURED, MOCK_BENCHMARK_RUN_DETAILS, getRunsForDefinition } from "@/mocks/engineSetupData";
import { TpcdsSetupDialog } from "@/components/LeftPanel/TpcdsWizard";
import type { Collection, CollectionWithQueries, BenchmarkSummary, BenchmarkDetail, BenchmarkRunDetail, BenchmarkRunSummary, BenchmarkRunProgress, BenchmarkStartResponse, ActiveBenchmarkRun, BenchmarkQueryResult, BenchmarkCancelResponse } from "@/types";
import { ArrowLeft, Plus, Trash2, X, Database, AlertTriangle, Lock, BarChart3, Clock, ExternalLink, Settings2, Activity, Square, CheckCircle2, XCircle, SkipForward } from "lucide-react";

export const CollectionsPanel: React.FC = () => {
  const {
    setEditorSql, setCollectionContext, refreshCollections, triggerRefreshCollections, activeCollectionId, setActiveCollectionId,
    engines, routingMode, benchmarkEngineIds, benchmarkDefinitions, reloadBenchmarkDefinitions, connectedWorkspace,
    benchmarkRunning, setBenchmarkRunning,
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
  const [benchmarkError, setBenchmarkError] = useState<string | null>(null);
  const [runsDialog, setRunsDialog] = useState<{ definitionId: number; engineName: string } | null>(null);

  // Active benchmark progress polling
  const [activeRunIds, setActiveRunIds] = useState<number[]>([]);
  const [runProgress, setRunProgress] = useState<Record<number, BenchmarkRunProgress>>({});

  // Live per-query results for active benchmark (keyed by run_id → results array)
  const [liveResults, setLiveResults] = useState<Record<number, BenchmarkQueryResult[]>>({});
  // Track the last result_id seen per run for incremental polling
  const lastResultIdRef = useRef<Record<number, number>>({});
  // Cancellation in-flight state (per run_id)
  const [cancellingRunIds, setCancellingRunIds] = useState<Set<number>>(new Set());
  // Toggle for collapsible live results feed
  const [showLiveResults, setShowLiveResults] = useState(false);

  const mock = isMockMode();

  // TPC-DS dataset configured check — detect via API in real mode
  const [tpcdsConfigured, setTpcdsConfigured] = useState(mock ? MOCK_TPCDS_CONFIGURED : false);
  const [showTpcdsSetup, setShowTpcdsSetup] = useState(false);

  // Detect TPC-DS on mount (real mode only)
  useEffect(() => {
    if (mock) return;
    api.get<Record<string, { found: boolean; registered?: boolean }>>("/api/tpcds/detect")
      .then(result => {
        const anyRegistered = Object.values(result).some(v => v.found && v.registered);
        setTpcdsConfigured(anyRegistered);
      })
      .catch(() => {
        // Detect failed (no workspace connected, etc.) — leave as unconfigured
      });
  }, [mock]);

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
      api.get<Collection[]>('/api/collections').then(async (cols) => {
        const full = await Promise.all(cols.map(c => api.get<CollectionWithQueries>(`/api/collections/${c.id}`)));
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
      api.get<CollectionWithQueries>(`/api/collections/${activeCollection.id}`).then(c => setActiveCollectionLocal(c));
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
        api.get<BenchmarkSummary[]>(`/api/benchmarks?collection_id=${activeCollectionId}`).then(b => setBenchmarks(b));
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
      c = await api.get<CollectionWithQueries>(`/api/collections/${id}`);
    }
    setActiveCollection(c);
    setSelectedQueryId(null);
    if (!mock) {
      const b = await api.get<BenchmarkSummary[]>(`/api/benchmarks?collection_id=${id}`);
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
      const created = await api.post<Collection>('/api/collections', { name: newName, description: newDesc });
      const full = await api.get<CollectionWithQueries>(`/api/collections/${created.id}`);
      setCollections(prev => [...prev, full]);
    }
    setShowCreate(false);
    setNewName("");
    setNewDesc("");
  };

  const handleDeleteCollection = async () => {
    if (deleteCollectionId === null) return;
    if (!mock) {
      await api.del(`/api/collections/${deleteCollectionId}`);
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
      await api.del(`/api/collections/${activeCollection.id}/queries/${deleteQueryId}`);
      const c = await api.get<CollectionWithQueries>(`/api/collections/${activeCollection.id}`);
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
    setBenchmarkRunning(true);
    setBenchmarkError(null);
    setLiveResults({});
    lastResultIdRef.current = {};
    try {
      const result = await api.post<BenchmarkStartResponse>('/api/benchmarks', { collection_id: activeCollection.id, engine_ids: engineIds });
      setActiveRunIds(result.run_ids);
      setRunProgress({});
    } catch (e: any) {
      const msg = e?.message || "Benchmark failed";
      if (msg.toLowerCase().includes("already running")) {
        setBenchmarkError("A benchmark is already running. Wait for it to finish.");
      } else {
        setBenchmarkError(msg);
      }
      setBenchmarkRunning(false);
    }
  };

  // Check for active benchmarks on mount (reconnect scenario)
  useEffect(() => {
    if (mock) return;
    api.get<ActiveBenchmarkRun[]>("/api/benchmarks/active").then(active => {
      if (active.length > 0) {
        setActiveRunIds(active.map(r => r.run_id));
        setBenchmarkRunning(true);
        // Seed progress from active data
        const progress: Record<number, BenchmarkRunProgress> = {};
        for (const r of active) {
          progress[r.run_id] = {
            run_id: r.run_id,
            definition_id: r.definition_id,
            status: r.status,
            engine_id: r.engine_id,
            engine_display_name: r.engine_display_name,
            collection_id: r.collection_id,
            collection_name: r.collection_name,
            total_queries: r.total_queries,
            completed_queries: r.completed_queries,
            failed_queries: r.failed_queries,
            elapsed_ms: 0,
            error_message: r.error_message,
          };
        }
        setRunProgress(progress);
      }
    }).catch(() => {});
  }, [mock]);

  // Poll progress + incremental results while benchmark is running
  useEffect(() => {
    if (activeRunIds.length === 0) return;

    const pollInterval = setInterval(async () => {
      const newProgress: Record<number, BenchmarkRunProgress> = {};
      let allDone = true;

      for (const runId of activeRunIds) {
        try {
          const p = await api.get<BenchmarkRunProgress>(`/api/benchmarks/runs/${runId}/progress`);
          newProgress[runId] = p;
          if (p.status !== "complete" && p.status !== "failed" && p.status !== "cancelled") {
            allDone = false;
          }
        } catch {
          // If progress fetch fails, keep previous state
          if (runProgress[runId]) {
            newProgress[runId] = runProgress[runId];
          }
          allDone = false;
        }

        // Poll incremental results for this run
        try {
          const since = lastResultIdRef.current[runId] ?? 0;
          const newResults = await api.get<BenchmarkQueryResult[]>(
            `/api/benchmarks/runs/${runId}/results`,
            { since: String(since) }
          );
          if (newResults.length > 0) {
            setLiveResults(prev => ({
              ...prev,
              [runId]: [...(prev[runId] ?? []), ...newResults],
            }));
            lastResultIdRef.current = {
              ...lastResultIdRef.current,
              [runId]: newResults[newResults.length - 1].result_id,
            };
          }
        } catch {
          // Results fetch failed — skip this cycle
        }
      }

      setRunProgress(newProgress);

      if (allDone) {
        // Benchmark finished — stop polling, refresh data
        clearInterval(pollInterval);
        setBenchmarkRunning(false);

        // Check for errors
        const failedRuns = Object.values(newProgress).filter(p => p.status === "failed");
        const completedRuns = Object.values(newProgress).filter(p => p.status === "complete");
        const cancelledRuns = Object.values(newProgress).filter(p => p.status === "cancelled");

        if (failedRuns.length > 0 && completedRuns.length === 0 && cancelledRuns.length === 0) {
          setBenchmarkError(`Benchmark failed: ${failedRuns[0].error_message || "unknown error"}`);
        } else if (failedRuns.length > 0) {
          setBenchmarkError(`${failedRuns.length}/${activeRunIds.length} engine(s) failed`);
        }

        // Refresh benchmarks list and definitions
        if (activeCollection) {
          api.get<BenchmarkSummary[]>(`/api/benchmarks?collection_id=${activeCollection.id}`)
            .then(setBenchmarks)
            .catch(() => {});
        }
        reloadBenchmarkDefinitions().catch(() => {});
        // Keep progress visible for a moment, then clear
        setTimeout(() => {
          setActiveRunIds([]);
          setRunProgress({});
          setLiveResults({});
          lastResultIdRef.current = {};
          setCancellingRunIds(new Set());
        }, 5000);
      }
    }, 2500);

    return () => clearInterval(pollInterval);
  }, [activeRunIds]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cancel a specific engine's benchmark run
  const handleCancelRun = async (runId: number) => {
    setCancellingRunIds(prev => new Set(prev).add(runId));
    try {
      await api.post<BenchmarkCancelResponse>(`/api/benchmarks/runs/${runId}/cancel`);
    } catch {
      // Cancel failed — remove from cancelling set
      setCancellingRunIds(prev => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
    }
  };

  const openBenchmarkDetail = async (id: number) => {
    const d = await api.get<BenchmarkDetail>(`/api/benchmarks/${id}`);
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
          <div className="text-[12px] text-muted-foreground">
            <p>Date: {new Date(benchmarkDetail.created_at).toLocaleString()}</p>
            <p>Engines: {benchmarkDetail.engine_count} | Queries: {queryIds.length}</p>
          </div>

          <div>
            <h4 className="font-semibold mb-1 text-foreground">Warm-up Times</h4>
            <table className="w-full border border-border text-[12px]">
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
              <table className="border-collapse border border-border text-[12px]" style={{ minWidth: "100%" }}>
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
              <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 text-[10px] font-medium flex items-center gap-0.5">
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
        <p className="px-3 py-1 text-[12px] text-muted-foreground">{activeCollection.description}</p>

        {/* TPC-DS dataset not configured warning */}
        {tpcdsNotConfigured && (
          <div className="mx-3 mt-1 mb-1 p-2 rounded border border-amber-200 bg-amber-50 flex items-start gap-2">
            <AlertTriangle size={13} className="text-amber-500 shrink-0 mt-0.5" />
            <div className="text-[11px]">
              <span className="font-medium text-amber-700">TPC-DS dataset not configured.</span>
              <span className="text-amber-600"> Set up the TPC-DS dataset to run benchmarks with this collection.</span>
              <button
                onClick={() => setShowTpcdsSetup(true)}
                className="mt-1.5 flex items-center gap-1 px-2 py-1 rounded bg-amber-100 hover:bg-amber-200 text-amber-800 text-[11px] font-medium transition-colors"
              >
                <Settings2 size={11} />
                Configure Dataset
              </button>
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
                  <span className="truncate font-mono text-[12px] text-foreground">{q.query_text.slice(0, 60)}</span>
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
              {/* Active benchmark dashboard */}
              {benchmarkRunning && activeRunIds.length > 0 && (
                <div className="space-y-3 mb-2">
                  <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
                    <Activity size={12} className="text-amber-500 animate-pulse" />
                    <span>Benchmark Running</span>
                  </div>

                  {/* Per-engine progress cards */}
                  {activeRunIds.map(runId => {
                    const p = runProgress[runId];
                    if (!p) return (
                      <div key={runId} className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <LoadingSpinner size={10} />
                        <span>Starting run #{runId}...</span>
                      </div>
                    );
                    const pct = p.total_queries > 0 ? Math.round((p.completed_queries / p.total_queries) * 100) : 0;
                    const elapsedSec = Math.round(p.elapsed_ms / 1000);
                    const minutes = Math.floor(elapsedSec / 60);
                    const seconds = elapsedSec % 60;
                    const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
                    const isDone = p.status === "complete" || p.status === "failed" || p.status === "cancelled";
                    const isCancelling = cancellingRunIds.has(runId);
                    const isActive = !isDone;

                    return (
                      <div key={runId} className={`rounded-md border p-2.5 space-y-1.5 ${
                        p.status === "cancelled" ? "border-amber-300 bg-amber-50/50" :
                        p.status === "failed" ? "border-red-200 bg-red-50/30" :
                        p.status === "complete" ? "border-emerald-200 bg-emerald-50/30" :
                        "border-border bg-card"
                      }`}>
                        {/* Header: engine name + status + stop button */}
                        <div className="flex items-center justify-between">
                          <span className={`text-[12px] font-medium ${
                            isDone
                              ? (p.status === "complete" ? "text-emerald-700" : p.status === "cancelled" ? "text-amber-700" : "text-red-700")
                              : "text-foreground"
                          }`}>
                            {p.engine_display_name}
                          </span>
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                              p.status === "complete" ? "bg-emerald-100 text-emerald-700" :
                              p.status === "failed" ? "bg-red-100 text-red-700" :
                              p.status === "cancelled" ? "bg-amber-100 text-amber-700" :
                              p.status === "warming_up" ? "bg-blue-100 text-blue-700" :
                              p.status === "pending" ? "bg-gray-100 text-gray-600" :
                              "bg-amber-100 text-amber-700"
                            }`}>
                              {p.status === "warming_up" ? "Warming up" :
                               p.status === "running" ? `${pct}%` :
                               p.status === "complete" ? "Done" :
                               p.status === "cancelled" ? (p.completed_queries === 0 ? "Skipped" : "Stopped") :
                               p.status === "failed" ? "Failed" :
                               p.status === "pending" ? "Queued" :
                               p.status}
                            </span>
                            {isActive && (
                              (() => {
                                const isRunningNow = p.status === "running" || p.status === "warming_up";
                                if (isRunningNow) {
                                  // Currently executing engine — Stop button
                                  return (
                                    <button
                                      onClick={() => handleCancelRun(runId)}
                                      disabled={isCancelling}
                                      className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
                                        isCancelling
                                          ? "bg-muted text-muted-foreground cursor-not-allowed"
                                          : "bg-red-50 text-red-600 hover:bg-red-100 border border-red-200"
                                      }`}
                                      title={isCancelling ? `Will stop after current query (Q${p.completed_queries + 1}) finishes` : "Stop after current query finishes"}
                                    >
                                      <Square size={8} />
                                      {isCancelling ? `Stopping after Q${p.completed_queries + 1}...` : "Stop"}
                                    </button>
                                  );
                                } else {
                                  // Pending/queued engine — Skip button
                                  return (
                                    <button
                                      onClick={() => handleCancelRun(runId)}
                                      disabled={isCancelling}
                                      className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
                                        isCancelling
                                          ? "bg-muted text-muted-foreground cursor-not-allowed"
                                          : "bg-amber-50 text-amber-700 hover:bg-amber-100 border border-amber-200"
                                      }`}
                                      title="Skip this engine — don't run it"
                                    >
                                      <SkipForward size={8} />
                                      {isCancelling ? "Skipping..." : "Skip"}
                                    </button>
                                  );
                                }
                              })()
                            )}
                          </div>
                        </div>

                        {/* Progress bar */}
                        <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-300 ${
                              p.status === "failed" ? "bg-red-500" :
                              p.status === "cancelled" ? "bg-amber-400" :
                              p.status === "complete" ? "bg-emerald-500" :
                              p.status === "warming_up" ? "bg-blue-400 animate-pulse" :
                              "bg-amber-500"
                            }`}
                            style={{ width: p.status === "warming_up" ? "5%" : `${Math.max(pct, 2)}%` }}
                          />
                        </div>

                        {/* Stats row */}
                        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                          <span>{p.completed_queries}/{p.total_queries} queries</span>
                          <div className="flex items-center gap-2">
                            {p.failed_queries > 0 && (
                              <span className="text-red-500">{p.failed_queries} failed</span>
                            )}
                            <span>{timeStr}</span>
                          </div>
                        </div>

                        {p.error_message && p.status === "failed" && (
                          <p className="text-[10px] text-red-600 truncate" title={p.error_message}>
                            {p.error_message}
                          </p>
                        )}
                      </div>
                    );
                  })}

                  {/* Live results feed — collapsible */}
                  {(() => {
                    // Merge all live results across runs, sorted newest first
                    const allResults = Object.entries(liveResults)
                      .flatMap(([runId, results]) => results.map(r => ({
                        ...r,
                        runId: Number(runId),
                        engineName: runProgress[Number(runId)]?.engine_display_name ?? `Run #${runId}`,
                      })))
                      .sort((a, b) => b.result_id - a.result_id);

                    if (allResults.length === 0) return null;

                    return (
                      <div className="mt-2">
                        <button
                          onClick={() => setShowLiveResults(prev => !prev)}
                          className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground mb-1 w-full"
                        >
                          <span className={`transition-transform text-[9px] ${showLiveResults ? "rotate-90" : ""}`}>▶</span>
                          Live Results ({allResults.length})
                        </button>
                        {showLiveResults && (
                        <div className="max-h-[200px] overflow-y-auto border border-border rounded">
                          <table className="w-full text-[10px]">
                            <thead className="sticky top-0 bg-muted z-10">
                              <tr>
                                <th className="text-left px-1.5 py-1 border-b border-border font-medium">Q#</th>
                                <th className="text-left px-1.5 py-1 border-b border-border font-medium">Engine</th>
                                <th className="text-left px-1.5 py-1 border-b border-border font-medium">Status</th>
                                <th className="text-right px-1.5 py-1 border-b border-border font-medium">Time</th>
                              </tr>
                            </thead>
                            <tbody>
                              {allResults.slice(0, 50).map(r => (
                                <tr key={r.result_id} className="even:bg-card/50">
                                  <td className="px-1.5 py-0.5 border-b border-border/50 font-mono">
                                    Q{r.sequence_number}
                                  </td>
                                  <td className="px-1.5 py-0.5 border-b border-border/50 truncate max-w-[80px]" title={r.engineName}>
                                    {r.engineName}
                                  </td>
                                  <td className="px-1.5 py-0.5 border-b border-border/50">
                                    {r.error_message ? (
                                      <span className="flex items-center gap-0.5 text-red-500" title={r.error_message}>
                                        <XCircle size={9} /> Fail
                                      </span>
                                    ) : (
                                      <span className="flex items-center gap-0.5 text-emerald-600">
                                        <CheckCircle2 size={9} /> OK
                                      </span>
                                    )}
                                  </td>
                                  <td className={`px-1.5 py-0.5 border-b border-border/50 text-right font-mono ${
                                    r.execution_time_ms != null ? latencyColor(r.execution_time_ms) : "text-muted-foreground"
                                  }`}>
                                    {r.execution_time_ms != null ? `${Math.round(r.execution_time_ms)}ms` : "—"}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* Run Benchmark button — hidden while benchmark is running */}
              {!benchmarkRunning && (
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
                          className={`px-3 py-1.5 rounded-md text-[12px] font-medium w-full ${
                            isDisabled
                              ? "bg-muted text-muted-foreground cursor-not-allowed"
                              : "bg-amber-600 text-white hover:bg-amber-700"
                          }`}
                        >
                          Run Benchmark
                        </button>
                        {!isBenchmarkMode && (
                          <p className="text-[11px] text-muted-foreground mt-1">
                            Switch to Benchmarking mode in the right panel to run benchmarks.
                          </p>
                        )}
                        {isBenchmarkMode && !hasEnginesSelected && (
                          <p className="text-[11px] text-amber-600 mt-1">
                            Select engines in the right panel to enable.
                          </p>
                        )}
                      </>
                    );
                  })()}
                  {benchmarkError && (
                    <p className="text-[12px] text-status-error mt-1">{benchmarkError}</p>
                  )}
                </>
              )}
            </div>
          )}

          {/* Runs by engine */}
          {collectionEngineRuns.length > 0 && (
            <div className="px-3 py-2 border-t border-panel-border">
              <div className="flex items-center gap-1.5 mb-1.5">
                <BarChart3 size={12} className="text-muted-foreground" />
                <span className="text-[12px] font-semibold text-foreground">Runs by Engine</span>
              </div>
              {collectionEngineRuns.map(({ definitionId, engineName, runCount }) => (
                <div
                  key={definitionId}
                  className="flex items-center justify-between px-2 py-1.5 hover:bg-muted/30 rounded text-[12px]"
                >
                  <span className="text-foreground font-medium truncate min-w-0">{engineName}</span>
                  {runCount > 0 ? (
                    <button
                      onClick={() => setRunsDialog({ definitionId, engineName })}
                      className="text-[11px] text-primary hover:underline shrink-0 ml-2"
                    >
                      {runCount} run{runCount !== 1 ? "s" : ""}
                    </button>
                  ) : (
                    <span className="text-[11px] text-muted-foreground shrink-0 ml-2">No runs</span>
                  )}
                </div>
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

        {/* TPC-DS Setup Dialog */}
        <TpcdsSetupDialog
          open={showTpcdsSetup}
          onClose={() => setShowTpcdsSetup(false)}
          onComplete={() => { setTpcdsConfigured(true); triggerRefreshCollections(); }}
        />
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

      <div className="px-3 py-2 text-[11px] text-muted-foreground border-b border-border">
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
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">TPC-DS Benchmarks</span>
              {!tpcdsConfigured && (
                <button
                  onClick={() => setShowTpcdsSetup(true)}
                  className="ml-auto flex items-center gap-0.5 text-[10px] text-amber-600 hover:text-amber-800 transition-colors"
                  title="Configure TPC-DS dataset"
                >
                  <AlertTriangle size={10} /> Set up
                </button>
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
                   <span className="text-[11px] text-muted-foreground">{c.queries.length} queries</span>
                 </div>
                 {c.description && (
                   <span className="text-[11px] text-muted-foreground truncate pl-[18px]">{c.description}</span>
                )}
              </button>
            ))}
          </>
        )}

        {/* User Collections */}
        {userCollections.length > 0 && (
          <>
            <div className="px-3 py-1.5 flex items-center gap-1.5 bg-muted/30 border-b border-border">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">User Collections</span>
            </div>
            {userCollections.map(c => (
              <button
                key={c.id}
                onClick={() => openCollection(c.id)}
                className="flex flex-col w-full px-3 py-2 hover:bg-muted text-left border-b border-border gap-0.5"
              >
                <div className="flex items-center justify-between w-full">
                  <span className="text-foreground font-medium">{c.name}</span>
                  <span className="text-[11px] text-muted-foreground">{c.queries.length} queries</span>
                </div>
                {c.description && (
                  <span className="text-[11px] text-muted-foreground truncate">{c.description}</span>
                )}
              </button>
            ))}
          </>
        )}

        {tpcdsCollections.length === 0 && userCollections.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] space-y-2">
            {!connectedWorkspace ? (
              <>
                <div className="text-muted-foreground font-medium">No collections yet</div>
                <div className="text-muted-foreground/70 leading-relaxed">
                  Connect a Databricks workspace to configure TPC-DS datasets and run benchmarks. You can also create custom query collections.
                </div>
              </>
            ) : !tpcdsConfigured ? (
              <>
                <div className="text-muted-foreground font-medium">No collections yet</div>
                <div className="text-muted-foreground/70 leading-relaxed">
                  Set up TPC-DS datasets to get pre-built benchmark collections with 99 queries, or create your own collection.
                </div>
                <button
                  onClick={() => setShowTpcdsSetup(true)}
                  className="mt-1 inline-flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200 rounded hover:bg-amber-100 transition-colors"
                >
                  <Settings2 size={11} /> Configure TPC-DS
                </button>
              </>
            ) : (
              <div className="text-muted-foreground">
                No collections yet. Create one to get started.
              </div>
            )}
          </div>
        )}
      </div>

      {/* TPC-DS Setup Dialog */}
      <TpcdsSetupDialog
        open={showTpcdsSetup}
        onClose={() => setShowTpcdsSetup(false)}
        onComplete={() => { setTpcdsConfigured(true); triggerRefreshCollections(); }}
      />
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
  const mock = isMockMode();
  const [runs, setRuns] = useState<BenchmarkRunDetail[]>(() =>
    mock ? getRunsForDefinition(definitionId) : []
  );
  const [runsLoading, setRunsLoading] = useState(!mock);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRunDetail | null>(null);
  const [view, setView] = useState<"runs" | "statistics">("runs");

  // Fetch runs from API in real mode
  useEffect(() => {
    if (mock) return;
    let cancelled = false;
    const fetchRuns = async () => {
      setRunsLoading(true);
      try {
        // First get run summaries
        const summaries = await api.get<BenchmarkRunSummary[]>(`/api/benchmarks/${definitionId}/runs`);
        // Fetch full detail for each run (warmups + results)
        const details = await Promise.all(
          summaries.map(s => api.get<BenchmarkRunDetail>(`/api/benchmarks/${definitionId}/runs/${s.id}`))
        );
        if (!cancelled) setRuns(details);
      } catch {
        if (!cancelled) setRuns([]);
      } finally {
        if (!cancelled) setRunsLoading(false);
      }
    };
    fetchRuns();
    return () => { cancelled = true; };
  }, [definitionId, mock]);

  const handleDeleteRun = async (runId: number) => {
    try {
      await api.del(`/api/benchmarks/${definitionId}/runs/${runId}`);
      setRuns(prev => prev.filter(r => r.id !== runId));
    } catch {
      // Deletion failed — ignore silently
    }
  };

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
                   : runsLoading
                     ? `${engineName} — loading...`
                     : `${engineName} — ${runs.length} run${runs.length !== 1 ? "s" : ""}`}
              </h3>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                {selectedRun
                  ? `${selectedRun.results.length} queries`
                  : view === "statistics"
                    ? "Aggregated statistics across all runs"
                    : "Click Details to view per-query results"}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted/50">
            <X size={14} />
          </button>
        </div>

        {/* Tab bar — only show when not drilled into a run detail */}
        {!selectedRun && runs.length >= 2 && (
          <div className="flex items-center gap-1 px-4 py-2 border-b border-border bg-muted/20 shrink-0">
            <button
              onClick={() => setView("runs")}
              className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                view === "runs" ? "bg-background text-foreground shadow-sm border border-border" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Runs
            </button>
            <button
              onClick={() => setView("statistics")}
              className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                view === "statistics" ? "bg-background text-foreground shadow-sm border border-border" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Statistics
            </button>
          </div>
        )}

        {/* Body */}
        <div className="overflow-y-auto flex-1">
          {runsLoading ? (
            <div className="px-4 py-6 text-center text-[12px] text-muted-foreground">Loading runs...</div>
          ) : selectedRun ? (
            <RunDetailView runDetail={selectedRun} />
          ) : view === "statistics" && runs.length >= 2 ? (
            <RunStatisticsView runs={runs} />
          ) : (
            <RunListView runs={runs} onViewDetail={setSelectedRun} onDeleteRun={mock ? undefined : handleDeleteRun} />
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
  onDeleteRun?: (runId: number) => void;
}> = ({ runs, onViewDetail, onDeleteRun }) => {
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  if (runs.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-[12px] text-muted-foreground">
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
            className={`flex items-center gap-3 px-4 py-2.5 text-[12px] ${
              idx > 0 ? "border-t border-border/50" : ""
            } hover:bg-muted/30 transition-colors`}
          >
            <Clock size={11} className="text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-foreground font-medium">{dateStr}</span>
                <span className="text-muted-foreground">{timeStr}</span>
                {run.status === "cancelled" && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded font-medium">Partial</span>
                )}
                {run.status === "failed" && (
                  <span className="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-700 rounded font-medium">Failed</span>
                )}
              </div>
              <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                <span>Total: <span className="font-mono text-foreground">{totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}</span></span>
                <span>{queryCount} quer{queryCount !== 1 ? "ies" : "y"}</span>
                {warmup && <span>Cold start: <span className={`font-mono ${latencyColor(warmup.cold_start_time_ms ?? 0)}`}>{warmup.cold_start_time_ms}ms</span></span>}
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => onViewDetail(run)}
                className="flex items-center gap-1 text-[11px] text-primary hover:underline"
              >
                Details <ExternalLink size={9} />
              </button>
              {onDeleteRun && (
                confirmDelete === run.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { onDeleteRun(run.id); setConfirmDelete(null); }}
                      className="text-[10px] px-1.5 py-0.5 bg-red-50 text-red-600 border border-red-200 rounded hover:bg-red-100"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmDelete(null)}
                      className="text-[10px] px-1.5 py-0.5 bg-muted text-muted-foreground rounded hover:bg-muted/80"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDelete(run.id)}
                    className="p-1 text-muted-foreground hover:text-red-500 rounded hover:bg-red-50/50 transition-colors"
                    title="Delete this run"
                  >
                    <Trash2 size={11} />
                  </button>
                )
              )}
            </div>
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
      <div className="flex items-center gap-4 mb-3 text-[12px]">
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
        <table className="w-full text-[11px]">
          <thead>
            <tr className="bg-muted">
              <th className="text-left px-2 py-1.5 border-b border-border font-semibold">Query</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Time (ms)</th>
              <th className="text-left px-3 py-1.5 border-b border-border font-semibold w-[40%]">Relative</th>
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
      <div className="flex items-center gap-4 mt-3 text-[11px] text-muted-foreground">
        <span>Min: <span className="font-mono text-foreground">{minMs}ms</span></span>
        <span>Max: <span className="font-mono text-foreground">{maxMs}ms</span></span>
        <span>Avg: <span className="font-mono text-foreground">{avgMs}ms</span></span>
        <span>Total: <span className="font-mono text-foreground">{totalMs >= 1000 ? `${(totalMs / 1000).toFixed(1)}s` : `${totalMs}ms`}</span></span>
      </div>
    </div>
  );
};

// ---- Run Statistics View (aggregate across all runs) ----

interface QueryStats {
  queryId: number;
  values: number[];
  avg: number;
  min: number;
  max: number;
  stddev: number;
  median: number;
}

const RunStatisticsView: React.FC<{ runs: BenchmarkRunDetail[] }> = ({ runs }) => {
  const stats = useMemo((): QueryStats[] => {
    // Collect all query IDs from all runs
    const queryMap = new Map<number, number[]>();
    for (const run of runs) {
      for (const result of run.results) {
        const ms = result.execution_time_ms;
        if (ms == null) continue;
        if (!queryMap.has(result.query_id)) queryMap.set(result.query_id, []);
        queryMap.get(result.query_id)!.push(ms);
      }
    }

    // Compute stats per query
    const result: QueryStats[] = [];
    for (const [queryId, values] of queryMap) {
      const sorted = [...values].sort((a, b) => a - b);
      const sum = values.reduce((a, b) => a + b, 0);
      const avg = sum / values.length;
      const min = sorted[0];
      const max = sorted[sorted.length - 1];
      const median = sorted.length % 2 === 0
        ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
        : sorted[Math.floor(sorted.length / 2)];
      const variance = values.reduce((s, v) => s + (v - avg) ** 2, 0) / values.length;
      const stddev = Math.sqrt(variance);
      result.push({ queryId, values, avg, min, max, stddev, median });
    }

    return result.sort((a, b) => a.queryId - b.queryId);
  }, [runs]);

  if (stats.length === 0) {
    return (
      <div className="px-4 py-6 text-center text-[12px] text-muted-foreground">
        No data available to compute statistics.
      </div>
    );
  }

  const globalMax = Math.max(...stats.map(s => s.max));
  const globalAvg = Math.round(stats.reduce((s, q) => s + q.avg, 0) / stats.length);
  const globalMin = Math.min(...stats.map(s => s.min));
  const globalMaxVal = Math.max(...stats.map(s => s.max));

  return (
    <div className="px-4 py-3">
      {/* Summary */}
      <div className="flex items-center gap-4 mb-3 text-[12px]">
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Runs:</span>
          <span className="font-mono text-foreground">{runs.length}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Queries:</span>
          <span className="font-mono text-foreground">{stats.length}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Avg across all:</span>
          <span className="font-mono text-foreground">{globalAvg}ms</span>
        </div>
      </div>

      {/* Per-query statistics table */}
      <div className="border border-border rounded overflow-hidden">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="bg-muted">
              <th className="text-left px-2 py-1.5 border-b border-border font-semibold">Query</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Avg (ms)</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Min</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Max</th>
              <th className="text-right px-2 py-1.5 border-b border-border font-semibold">Std</th>
              <th className="text-left px-3 py-1.5 border-b border-border font-semibold w-[25%]">Range</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s, i) => {
              // Range bar: min to max, relative to global max
              const minPct = globalMax > 0 ? (s.min / globalMax) * 100 : 0;
              const maxPct = globalMax > 0 ? (s.max / globalMax) * 100 : 0;
              const avgPct = globalMax > 0 ? (s.avg / globalMax) * 100 : 0;

              return (
                <tr key={s.queryId} className="even:bg-card/50">
                  <td className="px-2 py-1 border-b border-border font-mono text-foreground">Q{s.queryId}</td>
                  <td className={`px-2 py-1 border-b border-border text-right font-mono ${latencyColor(s.avg)}`}>
                    {Math.round(s.avg)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-right font-mono text-status-success">
                    {Math.round(s.min)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-right font-mono text-status-error">
                    {Math.round(s.max)}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-right font-mono text-muted-foreground">
                    {s.stddev < 1 ? s.stddev.toFixed(1) : Math.round(s.stddev)}
                  </td>
                  <td className="px-3 py-1.5 border-b border-border">
                    {/* Min-max range bar with avg marker */}
                    <div className="relative w-full h-3">
                      <div className="absolute top-1 w-full h-1 bg-muted rounded-full" />
                      {/* Range bar: min to max */}
                      <div
                        className="absolute top-0.5 h-2 bg-primary/20 rounded-full"
                        style={{ left: `${minPct}%`, width: `${Math.max(maxPct - minPct, 1)}%` }}
                      />
                      {/* Average marker */}
                      <div
                        className="absolute top-0 w-0.5 h-3 bg-primary rounded-full"
                        style={{ left: `${avgPct}%` }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Overall stats */}
      <div className="flex items-center gap-4 mt-3 text-[11px] text-muted-foreground">
        <span>Overall min: <span className="font-mono text-foreground">{globalMin}ms</span></span>
        <span>Overall max: <span className="font-mono text-foreground">{globalMaxVal}ms</span></span>
        <span>Mean avg: <span className="font-mono text-foreground">{globalAvg}ms</span></span>
        <span>Data points: <span className="font-mono text-foreground">{stats.reduce((s, q) => s + q.values.length, 0)}</span></span>
      </div>
    </div>
  );
};
