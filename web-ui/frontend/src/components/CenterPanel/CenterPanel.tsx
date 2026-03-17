import React, { useState } from "react";
import { useApp, useAuth } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { QueryExecutionResult } from "@/types";
import { Play, ChevronDown, ChevronRight } from "lucide-react";

export const CenterPanel: React.FC = () => {
  const { token } = useAuth();
  const { editorSql, setEditorSql, routingMode, queryResult, setQueryResult, collectionContext } = useApp();
  const [executing, setExecuting] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [logs, setLogs] = useState<any[]>([]);
  const [logFilter, setLogFilter] = useState("all");
  const [logsLoading, setLogsLoading] = useState(false);
  const [resultOpen, setResultOpen] = useState(true);

  const handleRun = async () => {
    if (!token || !editorSql.trim()) return;
    setExecuting(true);
    try {
      const result = await mockApi.executeQuery(token, editorSql, routingMode);
      setQueryResult(result);
    } catch {
      // ignore
    } finally {
      setExecuting(false);
    }
  };

  const loadLogs = async () => {
    if (!token) return;
    setLogsLoading(true);
    const l = await mockApi.getQueryLogs(token, logFilter === "all" ? undefined : logFilter);
    setLogs(l);
    setLogsLoading(false);
  };

  const toggleLog = () => {
    const next = !logOpen;
    setLogOpen(next);
    if (next) loadLogs();
  };

  const handleLogFilterChange = async (f: string) => {
    setLogFilter(f);
    if (!token || !logOpen) return;
    setLogsLoading(true);
    const l = await mockApi.getQueryLogs(token, f === "all" ? undefined : f);
    setLogs(l);
    setLogsLoading(false);
  };

  const isModified = collectionContext && editorSql !== collectionContext.originalSql;

  const latencyColor = (ms: number) => {
    if (ms < 100) return "text-status-success";
    if (ms < 500) return "text-status-warning";
    return "text-status-error";
  };

  return (
    <div className="flex flex-col h-full">
      {/* Editor */}
      <div className="flex-shrink-0 border-b border-panel-border">
        <textarea
          value={editorSql}
          onChange={e => setEditorSql(e.target.value)}
          placeholder={"-- Enter a SQL query here\nSELECT * FROM delta_router_dev.tpcds.customer LIMIT 10"}
          className="w-full h-48 resize-y p-3 font-mono text-[13px] bg-background text-foreground border-0 outline-none"
          spellCheck={false}
        />
      </div>

      {/* Action bar */}
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
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto">
        {!queryResult && !executing && (
          <div className="flex items-center justify-center h-full text-muted-foreground text-[13px]">
            Run a query to see results here.
          </div>
        )}
        {executing && (
          <div className="flex items-center justify-center h-32">
            <LoadingSpinner size={24} />
          </div>
        )}
        {queryResult && !executing && <ResultsView result={queryResult} resultOpen={resultOpen} setResultOpen={setResultOpen} latencyColor={latencyColor} />}
      </div>

      {/* Query Log */}
      <div className="border-t border-panel-border shrink-0">
        <button onClick={toggleLog} className="flex items-center gap-1 w-full px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-muted">
          {logOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Query Log
        </button>
        {logOpen && (
          <div className="max-h-48 overflow-y-auto border-t border-border">
            <div className="px-3 py-1">
              <select value={logFilter} onChange={e => handleLogFilterChange(e.target.value)} className="text-[11px] border border-border rounded px-1.5 py-0.5 bg-background text-foreground">
                <option value="all">All Engines</option>
                <option value="duckdb">DuckDB</option>
                <option value="databricks">Databricks</option>
              </select>
            </div>
            {logsLoading ? (
              <div className="p-3"><LoadingSpinner /></div>
            ) : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-muted">
                    <th className="text-left px-2 py-1 border-b border-border">Timestamp</th>
                    <th className="text-left px-2 py-1 border-b border-border">Query</th>
                    <th className="text-left px-2 py-1 border-b border-border">Engine</th>
                    <th className="text-center px-2 py-1 border-b border-border">Status</th>
                    <th className="text-right px-2 py-1 border-b border-border">Latency</th>
                    <th className="text-right px-2 py-1 border-b border-border">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((l, i) => (
                    <tr key={l.correlation_id} className={i % 2 ? "bg-card" : ""}>
                      <td className="px-2 py-1 border-b border-border whitespace-nowrap text-muted-foreground">{l.timestamp}</td>
                      <td className="px-2 py-1 border-b border-border max-w-[200px] truncate font-mono text-foreground">{l.query_text.slice(0, 60)}</td>
                      <td className="px-2 py-1 border-b border-border whitespace-nowrap text-foreground">{l.engine_display_name}</td>
                      <td className="px-2 py-1 border-b border-border text-center">
                        <StatusBadge variant={l.status === "success" ? "success" : "error"}>{l.status === "success" ? "Success" : "Error"}</StatusBadge>
                      </td>
                      <td className={`px-2 py-1 border-b border-border text-right ${latencyColor(l.latency_ms)}`}>{l.latency_ms}ms</td>
                      <td className="px-2 py-1 border-b border-border text-right text-foreground">${l.cost_usd.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const ResultsView: React.FC<{
  result: QueryExecutionResult;
  resultOpen: boolean;
  setResultOpen: (b: boolean) => void;
  latencyColor: (ms: number) => string;
}> = ({ result, resultOpen, setResultOpen, latencyColor }) => (
  <div className="p-3 space-y-3">
    {/* Routing Decision */}
    <div>
      <button onClick={() => setResultOpen(!resultOpen)} className="flex items-center gap-1 text-[12px] font-semibold text-foreground">
        {resultOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Routing Decision
      </button>
      {resultOpen && (
        <div className="mt-1 pl-4 space-y-1 text-[12px]">
          <p><span className="text-muted-foreground">Engine:</span> <StatusBadge variant={result.routing_decision.engine.startsWith("duckdb") ? "success" : "info"}>{result.routing_decision.engine_display_name}</StatusBadge></p>
          <p><span className="text-muted-foreground">Stage:</span> <span className="text-foreground">{result.routing_decision.stage.replace(/_/g, " ")}</span></p>
          <p><span className="text-muted-foreground">Reason:</span> <span className="text-foreground">{result.routing_decision.reason}</span></p>
          <p><span className="text-muted-foreground">Complexity:</span> <span className="text-foreground">{result.routing_decision.complexity_score}</span></p>
        </div>
      )}
    </div>

    {/* Metrics */}
    <div className="flex gap-4 text-[12px]">
      <span className={latencyColor(result.execution.execution_time_ms)}>⏱ {result.execution.execution_time_ms}ms</span>
      <span className="text-foreground">📊 {(result.execution.data_scanned_bytes / 1024 / 1024).toFixed(1)} MB</span>
      <span className="text-foreground">💰 ${result.execution.estimated_cost_usd.toFixed(4)}</span>
      {result.execution.cost_savings_usd > 0 && (
        <span className="text-status-success">💚 ${result.execution.cost_savings_usd.toFixed(4)} saved</span>
      )}
    </div>

    {/* Results Table */}
    <div className="overflow-auto border border-border rounded">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="bg-muted">
            {result.columns.map(c => (
              <th key={c} className="text-left px-2 py-1 border-b border-border font-mono font-medium text-foreground">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-card" : ""}>
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 border-b border-border font-mono text-foreground">{String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <p className="text-[11px] text-muted-foreground">Showing {result.rows.length} rows</p>
  </div>
);
