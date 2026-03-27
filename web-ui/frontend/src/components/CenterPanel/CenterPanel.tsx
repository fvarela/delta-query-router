import React, { useState, useCallback, useEffect, useRef } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { api } from "@/lib/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { QueryExecutionResult, LogEntry } from "@/types";
import { Play, Clock, Terminal, Info, X, FolderPlus } from "lucide-react";

/* ── colour helpers ── */

const levelColor: Record<string, string> = {
  info: "text-muted-foreground",
  rule: "text-status-success",
  decision: "text-primary",
  warn: "text-status-warning",
  error: "text-status-error",
};
const levelLabel: Record<string, string> = {
  info: "INFO", rule: "RULE", decision: "ROUTE", warn: "WARN", error: "ERROR",
};
const stageLabel: Record<string, string> = {
  parse: "PARSE", rules: "RULES", ml_model: "ML", engine: "ENGINE", execute: "EXEC", complete: "DONE",
};
const latencyColor = (ms: number) => {
  if (ms < 100) return "text-status-success";
  if (ms < 500) return "text-status-warning";
  return "text-status-error";
};

/* ── main component ── */

export const CenterPanel: React.FC = () => {
  const { editorSql, setEditorSql, runMode, singleEngineId, engines, queryResult, setQueryResult, collectionContext, activeCollectionId, triggerRefreshCollections } = useApp();
  const [executing, setExecuting] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logFilter, setLogFilter] = useState("all");
  const [modalEntry, setModalEntry] = useState<LogEntry | null>(null);
  const [modalLoading, setModalLoading] = useState(false);

  const isModified = collectionContext && editorSql !== collectionContext.originalSql;

  // "Add to Collection" state
  const [addingToCollection, setAddingToCollection] = useState(false);
  const [addedConfirm, setAddedConfirm] = useState(false);

  const handleAddToCollection = async () => {
    if (!activeCollectionId || !editorSql.trim()) return;
    setAddingToCollection(true);
    try {
      await mockApi.addQuery(activeCollectionId, editorSql.trim());
      triggerRefreshCollections();
      setAddedConfirm(true);
      setTimeout(() => setAddedConfirm(false), 2000);
    } finally {
      setAddingToCollection(false);
    }
  };

  /* load query history */
  const loadLogs = useCallback(async () => {
    try {
      const params = logFilter !== "all" ? { engine: logFilter } : undefined;
      const l = await api.get<LogEntry[]>("/api/logs", params);
      setLogs(l);
    } catch {
      // silently fail — user sees stale or empty history
    }
  }, [logFilter]);

  // Load history on mount and when filter changes
  useEffect(() => { loadLogs(); }, [loadLogs]);

  const handleRun = async () => {
    if (!editorSql.trim()) return;
    setExecuting(true);
    setModalEntry(null);
    try {
      let routing_mode = "smart";
      if (runMode === "single" && singleEngineId !== null) {
        const engine = engines.find(e => e.id === singleEngineId);
        if (engine) routing_mode = engine.engine_type === "duckdb" ? "duckdb" : "databricks";
      }

      const result = await api.post<QueryExecutionResult>("/api/query", { sql: editorSql, routing_mode });
      setQueryResult(result);
    } catch {
      // ignore — user sees no result update
    } finally {
      setExecuting(false);
      loadLogs();
    }
  };

  const handleRowClick = async (entry: LogEntry) => {
    if (entry.status === "running") return;
    setModalLoading(true);
    try {
      const detail = await api.get<{
        correlation_id: string;
        query_text: string;
        status: string;
        submitted_at: string;
        completed_at: string | null;
        routing_decision: {
          engine: string;
          engine_display_name: string;
          reason: string;
          complexity_score: number;
        };
      }>(`/api/query/${entry.correlation_id}`);
      // Merge backend detail into the LogEntry shape for the modal
      const enriched: LogEntry = {
        ...entry,
        routing_decision: {
          engine: detail.routing_decision.engine,
          engine_display_name: detail.routing_decision.engine_display_name,
          stage: "fallback", // backend doesn't persist stage yet
          reason: detail.routing_decision.reason,
          complexity_score: detail.routing_decision.complexity_score,
        },
      };
      setModalEntry(enriched);
    } catch {
      // Fallback: show modal with whatever we have from the log entry
      setModalEntry(entry);
    } finally {
      setModalLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── Query Editor (fixed) ── */}
      <div className="shrink-0 border-b border-panel-border">
        <textarea
          value={editorSql}
          onChange={e => setEditorSql(e.target.value)}
          placeholder={"-- Enter a SQL query here\nSELECT * FROM delta_router_dev.tpcds.customer LIMIT 10"}
          className="w-full h-48 resize-y p-3 font-mono text-[13px] bg-background text-foreground border-0 outline-none"
          spellCheck={false}
        />
      </div>

      {/* ── Action bar (fixed) ── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-panel-border bg-card shrink-0">
        <button
          onClick={handleRun}
          disabled={executing || !editorSql.trim()}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium disabled:opacity-50"
        >
          {executing ? <LoadingSpinner size={14} /> : <Play size={13} />}
          Run
        </button>
        {collectionContext && (
          <span className={`text-[11px] px-2 py-0.5 rounded ${isModified ? "bg-status-warning/20 text-status-warning" : "bg-muted text-muted-foreground"}`}>
            From: {collectionContext.collectionName} / {collectionContext.queryLabel}
            {isModified && " (Modified)"}
          </span>
        )}
        {/* Add to Collection button — visible when a collection is open and editor has content */}
        {activeCollectionId && editorSql.trim() && (
          <button
            onClick={handleAddToCollection}
            disabled={addingToCollection}
            className="flex items-center gap-1 ml-auto px-3 py-1.5 border border-border rounded-md text-[11px] font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            <FolderPlus size={12} />
            {addedConfirm ? "Added!" : "Add to Collection"}
          </button>
        )}
      </div>

      {/* ── Results area (fixed, non-scrollable, max 10 rows) ── */}
      <div className="shrink-0">
        {!queryResult && !executing && (
          <div className="flex items-center justify-center h-24 text-muted-foreground text-[13px]">
            Run a query to see results here.
          </div>
        )}
        {executing && !queryResult && (
          <div className="flex items-center justify-center h-20">
            <LoadingSpinner size={24} />
          </div>
        )}
        {queryResult && <ResultsView result={queryResult} />}
      </div>

      {/* ── Query History (scrollable, takes remaining space) ── */}
      <div className="flex-1 min-h-0 flex flex-col border-t border-panel-border">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-card shrink-0">
          <Clock size={12} className="text-muted-foreground" />
          <span className="text-[12px] font-semibold text-foreground">Query History</span>
          <select
            value={logFilter}
            onChange={e => { setLogFilter(e.target.value); }}
            className="ml-auto text-[11px] border border-border rounded px-1.5 py-0.5 bg-background text-foreground"
          >
            <option value="all">All Engines</option>
            <option value="duckdb">DuckDB</option>
            <option value="databricks">Databricks</option>
          </select>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto border-t border-border">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-muted">
                <th className="text-left px-2 py-1 border-b border-border">Time</th>
                <th className="text-left px-2 py-1 border-b border-border">Query</th>
                <th className="text-left px-2 py-1 border-b border-border">Engine</th>
                <th className="text-center px-2 py-1 border-b border-border">Status</th>
                <th className="text-right px-2 py-1 border-b border-border">Latency</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l, i) => (
                <tr
                  key={l.correlation_id}
                  onClick={() => handleRowClick(l)}
                  className={`${i % 2 ? "bg-card" : ""} ${l.status !== "running" ? "cursor-pointer hover:bg-primary/5" : ""}`}
                >
                  <td className="px-2 py-1 border-b border-border whitespace-nowrap text-muted-foreground">
                    {l.timestamp.slice(11, 19) || l.timestamp}
                  </td>
                  <td className="px-2 py-1 border-b border-border max-w-[200px] truncate font-mono text-foreground">
                    {l.query_text.slice(0, 60)}
                  </td>
                  <td className="px-2 py-1 border-b border-border whitespace-nowrap text-foreground">
                    {l.status === "running" ? <span className="text-muted-foreground italic">routing...</span> : l.engine_display_name}
                  </td>
                  <td className="px-2 py-1 border-b border-border text-center">
                    {l.status === "running" ? (
                      <span className="inline-flex items-center gap-1 text-primary text-[10px] font-medium">
                        <LoadingSpinner size={10} /> Running
                      </span>
                    ) : (
                      <StatusBadge variant={l.status === "success" ? "success" : "error"}>
                        {l.status === "success" ? "Success" : "Error"}
                      </StatusBadge>
                    )}
                  </td>
                  <td className={`px-2 py-1 border-b border-border text-right ${l.status === "running" ? "text-muted-foreground" : latencyColor(l.latency_ms)}`}>
                    {l.status === "running" ? "—" : `${l.latency_ms}ms`}
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-muted-foreground text-[12px]">
                    No queries yet. Run a query to see history here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Query Detail Modal ── */}
      {modalEntry && (
        <QueryDetailModal
          entry={modalEntry}
          onClose={() => setModalEntry(null)}
        />
      )}
    </div>
  );
};

/* ── Results View (metrics + data table, non-scrollable, max 10 rows) ── */

const ResultsView: React.FC<{ result: QueryExecutionResult }> = ({ result }) => (
  <div className="p-3 space-y-2">
    {/* Metrics */}
    <div className="flex gap-4 text-[12px]">
      <span className={latencyColor(result.execution.execution_time_ms)}>Time: {result.execution.execution_time_ms}ms</span>
      <span className="text-foreground">Scanned: {(result.execution.data_scanned_bytes / 1024 / 1024).toFixed(1)} MB</span>
    </div>

    {/* Results Table (max 10 rows, no scroll) */}
    <div className="border border-border rounded">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="bg-muted">
            {result.columns.map(c => (
              <th key={c} className="text-left px-2 py-1 border-b border-border font-mono font-medium text-foreground">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.slice(0, 10).map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-card" : ""}>
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 border-b border-border font-mono text-foreground">{String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <p className="text-[11px] text-muted-foreground">
      Showing {Math.min(result.rows.length, 10)} of {result.rows.length} rows
    </p>
  </div>
);

/* ── Query Detail Modal ── */

const QueryDetailModal: React.FC<{
  entry: LogEntry;
  onClose: () => void;
}> = ({ entry, onClose }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const events = entry.routing_events || [];
  const decision = entry.routing_decision;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-card border border-border rounded-lg shadow-xl w-[700px] max-w-[90vw] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div>
            <h3 className="text-[13px] font-semibold text-foreground">Query Details</h3>
            <p className="text-[11px] text-muted-foreground font-mono mt-0.5 max-w-[550px] truncate">
              {entry.query_text}
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground">
            <X size={16} />
          </button>
        </div>

        {/* Summary row */}
        <div className="flex items-center gap-4 px-4 py-2 border-b border-border text-[11px] shrink-0">
          <span className="text-muted-foreground">{entry.timestamp}</span>
          <span className="text-foreground">{entry.engine_display_name}</span>
          <StatusBadge variant={entry.status === "success" ? "success" : "error"}>
            {entry.status === "success" ? "Success" : "Error"}
          </StatusBadge>
          <span className={latencyColor(entry.latency_ms)}>{entry.latency_ms}ms</span>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {/* Routing Decision */}
          {decision && (
            <div className="px-4 py-3 border-b border-border">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground mb-2">
                <Info size={11} />
                <span className="font-semibold">Routing Decision</span>
              </div>
              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                <span className="text-muted-foreground">Engine</span>
                <span><StatusBadge variant={decision.engine.startsWith("duckdb") ? "success" : "info"}>{decision.engine_display_name}</StatusBadge></span>
                <span className="text-muted-foreground">Stage</span>
                <span className="text-foreground">{decision.stage.replace(/_/g, " ")}</span>
                <span className="text-muted-foreground">Reason</span>
                <span className="text-foreground">{decision.reason}</span>
                <span className="text-muted-foreground">Complexity</span>
                <span className="text-foreground">{decision.complexity_score}</span>

                {/* Decomposed latency (ODQ-9 / ODQ-10) */}
                {decision.total_latency_ms != null && (
                  <>
                    <span className="text-muted-foreground">Latency</span>
                    <span className="text-foreground font-mono">
                      Compute: {decision.compute_time_ms ?? "?"}ms
                      {decision.io_latency_ms != null && <> + I/O: {decision.io_latency_ms}ms</>}
                      {decision.cold_start_ms != null && decision.cold_start_ms > 0 && <> + Cold: {decision.cold_start_ms}ms</>}
                      {" "}= <span className={latencyColor(decision.total_latency_ms)}>{decision.total_latency_ms}ms</span>
                    </span>
                  </>
                )}
                {decision.weighted_score != null && (
                  <>
                    <span className="text-muted-foreground">Scoring</span>
                    <span className="text-foreground font-mono text-[10px]">
                      Latency: {decision.latency_score?.toFixed(2) ?? "—"}
                      {" · "}Cost Tier: {decision.cost_score?.toFixed(2) ?? "—"}
                      {" · "}<span className="font-semibold">Weighted: {decision.weighted_score.toFixed(2)}</span>
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Routing Log */}
          {events.length > 0 && (
            <div className="bg-[#1a1a2e]">
              <div className="flex items-center gap-1.5 px-4 py-1.5 border-b border-white/10">
                <Terminal size={11} className="text-primary" />
                <span className="text-[11px] font-semibold text-[#888]">Routing Log</span>
                <span className="text-[10px] text-[#666]">({events.length} events)</span>
              </div>
              <div ref={scrollRef} className="p-3 font-mono text-[11px] leading-relaxed">
                {events.map((ev, i) => (
                  <div key={i} className="flex gap-2 py-px hover:bg-white/5">
                    <span className="text-[#666] shrink-0 select-none">{ev.timestamp}</span>
                    <span className={`shrink-0 w-[42px] text-right font-semibold ${levelColor[ev.level] || "text-muted-foreground"}`}>
                      {levelLabel[ev.level] || ev.level}
                    </span>
                    <span className="shrink-0 w-[48px] text-[#888]">
                      [{stageLabel[ev.stage] || ev.stage}]
                    </span>
                    <span className={`${ev.level === "decision" ? "text-primary font-semibold" : ev.level === "rule" ? "text-status-success" : ev.level === "warn" ? "text-status-warning" : ev.level === "error" ? "text-status-error" : "text-[#ccc]"}`}>
                      {ev.message}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* No detail available */}
          {!decision && events.length === 0 && (
            <div className="px-4 py-6 text-center text-[12px] text-muted-foreground">
              No routing details available for this query.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
