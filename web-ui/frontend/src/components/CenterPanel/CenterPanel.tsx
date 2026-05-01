import React, { useState, useCallback, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { api } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";
import { parseRoutingEvents } from "@/lib/routingEventParser";
import type { RoutingDecisionData } from "@/lib/routingEventParser";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { RoutingDecisionView } from "./RoutingDecisionView";
import type { QueryExecutionResult, LogEntry, RoutingLogEvent, Query } from "@/types";
import { Play, Clock, FolderPlus } from "lucide-react";

/* ── colour helpers ── */

const latencyColor = (ms: number) => {
  if (ms < 100) return "text-status-success";
  if (ms < 500) return "text-status-warning";
  return "text-status-error";
};

/* ── main component ── */

export const CenterPanel: React.FC = () => {
  const { editorSql, setEditorSql, runMode, singleEngineId, engines, queryResult, setQueryResult, collectionContext, activeCollectionId, triggerRefreshCollections, enabledEngineIds, warehouseMappings, routingSettings } = useApp();
  const [executing, setExecuting] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logFilter, setLogFilter] = useState("all");
  const [modalData, setModalData] = useState<RoutingDecisionData | null>(null);
  const [modalLoading, setModalLoading] = useState(false);

  const isModified = collectionContext && editorSql !== collectionContext.originalSql;

  // "Add to Collection" state
  const [addingToCollection, setAddingToCollection] = useState(false);
  const [addedConfirm, setAddedConfirm] = useState(false);

  const handleAddToCollection = async () => {
    if (!activeCollectionId || !editorSql.trim()) return;
    setAddingToCollection(true);
    try {
      await api.post<Query>(`/api/collections/${activeCollectionId}/queries`, { query_text: editorSql.trim() });
      triggerRefreshCollections();
      setAddedConfirm(true);
      setTimeout(() => setAddedConfirm(false), 2000);
    } finally {
      setAddingToCollection(false);
    }
  };

  /* load query history — use mock API in mock mode (UX #30) */
  const mock = isMockMode();
  const loadLogs = useCallback(async () => {
    try {
      if (mock) {
        const l = await mockApi.getQueryLogs(logFilter !== "all" ? logFilter : undefined);
        setLogs(l);
      } else {
        const params = logFilter !== "all" ? { engine: logFilter } : undefined;
        const l = await api.get<LogEntry[]>("/api/logs", params);
        setLogs(l);
      }
    } catch {
      // silently fail — user sees stale or empty history
    }
  }, [logFilter, mock]);

  // Load history on mount and when filter changes
  useEffect(() => { loadLogs(); }, [loadLogs]);

  const handleRun = async () => {
    if (!editorSql.trim()) return;
    setExecuting(true);
    setModalData(null);
    setQueryError(null);
    setQueryResult(null);
    try {
      let routing_mode = "smart";
      if (runMode === "single" && singleEngineId !== null) {
        const engine = engines.find(e => e.id === singleEngineId);
        if (engine) routing_mode = engine.engine_type === "duckdb" ? "duckdb" : "databricks";
      }

      // UX #28: Route through mock API in mock mode
      if (mock) {
        const result = await mockApi.executeQuery(editorSql, routing_mode);
        setQueryResult(result);
      } else {
        // Only include engines that can actually execute: DuckDB engines are always
        // executable, Databricks engines need a warehouse mapped
        const executableEngineIds = [...enabledEngineIds].filter(id => {
          const eng = engines.find(e => e.id === id);
          if (!eng) return false;
          if (eng.engine_type === "duckdb") return true;
          // Databricks: only if warehouse is mapped
          const mapping = warehouseMappings.find(m => m.engineId === id);
          return mapping?.warehouseId != null;
        });
        const result = await api.post<QueryExecutionResult>("/api/query", {
          sql: editorSql,
          routing_mode,
          enabled_engine_ids: executableEngineIds,
        });
        setQueryResult(result);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Query execution failed";
      setQueryError(message);
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
          stage?: string;
          compute_time_ms?: number;
          cold_start_ms?: number;
          total_latency_ms?: number;
        };
        routing_log_events?: RoutingLogEvent[];
      }>(`/api/query/${entry.correlation_id}`);

      const events = detail.routing_log_events ?? [];
      const parsed = parseRoutingEvents(
        events,
        detail.routing_decision,
        detail.query_text,
        entry.latency_ms,
        { engines, routingSettings, enabledEngineIds, warehouseMappings },
      );
      setModalData(parsed);
    } catch {
      // Fallback: build minimal data from the log entry itself
      if (entry.routing_decision) {
        const events = entry.routing_events ?? [];
        const parsed = parseRoutingEvents(
          events,
          entry.routing_decision,
          entry.query_text,
          entry.latency_ms,
          { engines, routingSettings, enabledEngineIds, warehouseMappings },
        );
        setModalData(parsed);
      }
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
          className="sql-editor w-full h-48 resize-y p-3 font-mono text-[13px] text-foreground m-0 rounded-none border-x-0 border-t-0"
          spellCheck={false}
        />
      </div>

      {/* ── Action bar (fixed) ── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-panel-border bg-card shrink-0 shadow-section">
        <button
          onClick={handleRun}
          disabled={executing || !editorSql.trim()}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-semibold disabled:opacity-50 hover:bg-primary/90 transition-colors shadow-sm"
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
            className="flex items-center gap-1 ml-auto px-3 py-1.5 border border-border rounded-md text-[11px] font-medium text-foreground hover:bg-muted disabled:opacity-50 transition-colors"
          >
            <FolderPlus size={12} />
            {addedConfirm ? "Added!" : "Add to Collection"}
          </button>
        )}
      </div>

      {/* ── Results area (bounded, scrollable) ── */}
      <div className="shrink-0 max-h-[40%] overflow-y-auto">
        {!queryResult && !executing && !queryError && (
          <div className="flex items-center justify-center h-24 text-muted-foreground text-[13px]">
            Run a query to see results here.
          </div>
        )}
        {executing && (
          <div className="flex items-center justify-center h-20">
            <LoadingSpinner size={24} />
          </div>
        )}
        {queryError && !executing && (
          <div className="mx-3 my-2 p-3 rounded-md border border-status-error/30 bg-status-error/10">
            <div className="flex items-start gap-2">
              <span className="text-status-error text-[12px] font-semibold shrink-0">Error</span>
              <p className="text-[12px] text-status-error/90 font-mono break-all">{queryError}</p>
            </div>
          </div>
        )}
        {queryResult && !executing && <ResultsView result={queryResult} />}
      </div>

      {/* ── Query History (scrollable, takes remaining space) ── */}
      <div className="flex-1 min-h-0 flex flex-col border-t border-panel-border">
        <div className="flex items-center gap-2 px-3 py-2 bg-card shrink-0 shadow-section">
          <Clock size={13} className="text-muted-foreground" />
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
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-muted">
                <th className="text-left px-2 py-1.5 border-b border-border font-medium text-muted-foreground">Date/Time</th>
                <th className="text-left px-2 py-1.5 border-b border-border font-medium text-muted-foreground">Query</th>
                <th className="text-left px-2 py-1.5 border-b border-border font-medium text-muted-foreground">Engine</th>
                <th className="text-center px-2 py-1.5 border-b border-border font-medium text-muted-foreground">Status</th>
                <th className="text-right px-2 py-1.5 border-b border-border font-medium text-muted-foreground">Latency</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l, i) => (
                <tr
                  key={l.correlation_id}
                  onClick={() => handleRowClick(l)}
                  className={`${i % 2 ? "bg-card" : ""} ${l.status !== "running" ? "cursor-pointer hover:bg-primary/5" : ""}`}
                >
                  <td className="px-2 py-1.5 border-b border-border whitespace-nowrap text-muted-foreground">
                    {new Date(l.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </td>
                  <td className="px-2 py-1.5 border-b border-border max-w-[200px] truncate font-mono text-foreground">
                    {l.query_text.slice(0, 60)}
                  </td>
                  <td className="px-2 py-1.5 border-b border-border whitespace-nowrap text-foreground">
                    {l.status === "running" ? <span className="text-muted-foreground italic">routing...</span> : l.engine_display_name}
                  </td>
                  <td className="px-2 py-1.5 border-b border-border text-center">
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
                  <td className={`px-2 py-1.5 border-b border-border text-right font-mono ${l.status === "running" ? "text-muted-foreground" : latencyColor(l.latency_ms)}`}>
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
      {modalData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50" onClick={() => setModalData(null)} />
          <div className="relative bg-card border border-border rounded-lg shadow-xl w-[750px] max-w-[90vw] max-h-[80vh] flex flex-col">
            <RoutingDecisionView data={modalData} onClose={() => setModalData(null)} />
          </div>
        </div>
      )}
    </div>
  );
};

/* ── Results View (metrics + data table, scrollable) ── */

const ResultsView: React.FC<{ result: QueryExecutionResult }> = ({ result }) => (
  <div className="p-3 space-y-2">
    {/* Metrics */}
    <div className="flex gap-4 text-[12px]">
      <span className={latencyColor(result.execution.execution_time_ms)}>Time: {result.execution.execution_time_ms}ms</span>
    </div>

    {/* Results Table (max 10 rows, horizontally scrollable) */}
    <div className="border border-border rounded-md overflow-x-auto shadow-section">
      <table className="min-w-full text-[12px]">
        <thead>
          <tr className="bg-muted">
            {result.columns.map(c => (
              <th key={c} className="text-left px-2 py-1.5 border-b border-border font-mono font-medium text-foreground whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.slice(0, 10).map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-card" : ""}>
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 border-b border-border font-mono text-foreground whitespace-nowrap">{String(cell)}</td>
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

