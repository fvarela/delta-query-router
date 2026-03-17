import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth, useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { Collection, CollectionWithQueries, BenchmarkSummary, BenchmarkDetail } from "@/types";
import { ArrowLeft, Plus, Trash2, X } from "lucide-react";

export const RightPanel: React.FC = () => {
  const { token } = useAuth();
  const { setEditorSql, setCollectionContext, refreshCollections } = useApp();
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeCollection, setActiveCollection] = useState<CollectionWithQueries | null>(null);
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
  const [benchmarkStage, setBenchmarkStage] = useState("");

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    mockApi.getCollections(token).then(c => { setCollections(c); setLoading(false); });
  }, [token, refreshCollections]);

  const openCollection = async (id: number) => {
    if (!token) return;
    const c = await mockApi.getCollection(token, id);
    setActiveCollection(c);
    setSelectedQueryId(null);
    const b = await mockApi.getBenchmarks(token, id);
    setBenchmarks(b);
    setBenchmarkDetail(null);
  };

  const handleCreate = async () => {
    if (!token || !newName) return;
    await mockApi.createCollection(token, newName, newDesc);
    const c = await mockApi.getCollections(token);
    setCollections(c);
    setShowCreate(false);
    setNewName("");
    setNewDesc("");
  };

  const handleDeleteCollection = async () => {
    if (!token || deleteCollectionId === null) return;
    await mockApi.deleteCollection(token, deleteCollectionId);
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
    if (!token || !activeCollection || deleteQueryId === null) return;
    await mockApi.deleteQuery(token, activeCollection.id, deleteQueryId);
    const c = await mockApi.getCollection(token, activeCollection.id);
    setActiveCollection(c);
    setDeleteQueryId(null);
  };

  const handleRunBenchmark = async () => {
    if (!token || !activeCollection) return;
    setRunningBenchmark(true);
    const stages = ["Provisioning engines...", "Warming up engines...", "Running queries...", "Cleaning up temporary engines...", "Complete"];
    for (const stage of stages) {
      setBenchmarkStage(stage);
      await new Promise(r => setTimeout(r, 2000));
    }
    await mockApi.createBenchmark(token, activeCollection.id, [1, 4, 5]);
    const b = await mockApi.getBenchmarks(token, activeCollection.id);
    setBenchmarks(b);
    setRunningBenchmark(false);
    setBenchmarkStage("");
  };

  const openBenchmarkDetail = async (id: number) => {
    if (!token) return;
    const d = await mockApi.getBenchmark(token, id);
    setBenchmarkDetail(d);
  };

  if (loading) return <div className="p-3"><LoadingSpinner /></div>;

  // Benchmark Detail View
  if (benchmarkDetail) {
    const engines = [...new Set(benchmarkDetail.results.map(r => r.engine_display_name))];
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
                    <td className="px-2 py-1 border-b border-border text-right text-foreground">{w.cold_start_time_ms.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h4 className="font-semibold mb-1 text-foreground">Results (ms)</h4>
            <table className="w-full border border-border text-[11px]">
              <thead>
                <tr className="bg-muted">
                  <th className="text-left px-2 py-1 border-b border-border">Query</th>
                  {engines.map(e => <th key={e} className="text-right px-2 py-1 border-b border-border">{e}</th>)}
                </tr>
              </thead>
              <tbody>
                {queryIds.map((qId, i) => {
                  const row = engines.map(e => benchmarkDetail.results.find(r => r.query_id === qId && r.engine_display_name === e)?.execution_time_ms ?? 0);
                  const min = Math.min(...row);
                  const max = Math.max(...row);
                  return (
                    <tr key={qId} className={i % 2 ? "bg-card" : ""}>
                      <td className="px-2 py-1 border-b border-border font-medium text-foreground">Q{i + 1}</td>
                      {row.map((v, j) => (
                        <td key={j} className={`px-2 py-1 border-b border-border text-right ${v === min ? "text-status-success font-semibold" : v === max ? "text-status-error" : "text-foreground"}`}>
                          {v.toLocaleString()}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  // Collection Detail View
  if (activeCollection) {
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-2 border-b border-panel-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button onClick={() => { setActiveCollection(null); setCollectionContext(null); }}><ArrowLeft size={14} /></button>
            <span className="font-semibold text-foreground">{activeCollection.name}</span>
          </div>
          <button onClick={() => setDeleteCollectionId(activeCollection.id)} className="text-muted-foreground hover:text-status-error">
            <Trash2 size={13} />
          </button>
        </div>
        <p className="px-3 py-1 text-[11px] text-muted-foreground">{activeCollection.description}</p>

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
                  <span className="truncate font-mono text-[11px] text-foreground">{q.query_text.slice(0, 80)}</span>
                </div>
                <button onClick={e => { e.stopPropagation(); setDeleteQueryId(q.id); }} className="text-muted-foreground hover:text-status-error shrink-0 ml-1">
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>

          {/* Benchmark section */}
          <div className="px-3 py-2 border-t border-panel-border">
            {runningBenchmark ? (
              <div className="space-y-2">
                <LoadingSpinner />
                <p className="text-[11px] text-muted-foreground">{benchmarkStage}</p>
              </div>
            ) : (
              <button
                onClick={handleRunBenchmark}
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[11px] font-medium w-full"
              >
                Run Benchmark
              </button>
            )}
          </div>

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
                    <StatusBadge variant={b.status === "complete" ? "success" : "error"}>{b.status}</StatusBadge>
                    <span className="text-muted-foreground">{b.engine_count} engines</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <ConfirmDialog open={deleteCollectionId !== null} title="Delete Collection" description={`Delete collection '${activeCollection.name}' and all its queries? This cannot be undone.`} onConfirm={handleDeleteCollection} onCancel={() => setDeleteCollectionId(null)} destructive />
        <ConfirmDialog open={deleteQueryId !== null} title="Remove Query" description="Remove this query from the collection?" onConfirm={handleDeleteQuery} onCancel={() => setDeleteQueryId(null)} destructive />
      </div>
    );
  }

  // Collection List View
  return (
    <div className="flex flex-col h-full text-[12px]">
      <div className="px-3 py-2 border-b border-panel-border flex items-center justify-between">
        <span className="font-semibold text-foreground">Collections</span>
        <button onClick={() => setShowCreate(true)} className="text-primary hover:text-primary/80"><Plus size={14} /></button>
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
        {collections.map(c => (
          <button
            key={c.id}
            onClick={() => openCollection(c.id)}
            className="flex items-center justify-between w-full px-3 py-2 hover:bg-muted text-left border-b border-border"
          >
            <span className="text-foreground">{c.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
