import React, { useState } from "react";
import { useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { HardDrive, ChevronDown, ChevronRight, Info } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

/** Compact section showing storage latency probe results.
 *  Placed in the Routing tab below the Engines table.
 *  Only visible when at least one DuckDB engine is enabled.
 */
export const StorageLatencySection: React.FC = () => {
  const { storageProbes, runStorageProbes, probesRunning, engines, enabledEngineIds, connectedWorkspace } = useApp();
  const [expanded, setExpanded] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);

  // Only show when at least one DuckDB engine is enabled
  const hasDuckDb = engines.some(e =>
    e.engine_type === "duckdb" && enabledEngineIds.has(e.id)
  );
  if (!hasDuckDb) return null;

  const formatLatency = (ms: number) => `${ms.toFixed(0)} ms`;
  const formatBytes = (b: number) => {
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
    return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  };
  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  // Count unique probed locations
  const uniqueLocations = new Set(storageProbes.map(p => p.storage_location)).size;

  return (
    <>
    <div className="text-[12px]">
      <div className="px-3 py-1.5 border-b border-panel-border flex items-center justify-between">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 flex-1 min-w-0"
        >
          {expanded ? <ChevronDown size={12} className="text-muted-foreground shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground shrink-0" />}
          <HardDrive size={12} className="text-primary shrink-0" />
          <span className="font-semibold text-foreground">Storage Latency</span>
          <span className="text-[10px] text-muted-foreground">
            ({uniqueLocations > 0 ? `${uniqueLocations} location${uniqueLocations !== 1 ? "s" : ""} probed` : "no probes"})
          </span>
        </button>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={() => setShowInfoModal(true)}
            className="text-muted-foreground hover:text-primary transition-colors"
            title="How Storage Latency works"
          >
            <Info size={12} />
          </button>
          {expanded && (
            <button
              onClick={runStorageProbes}
              disabled={probesRunning}
              className="px-2 py-0.5 text-[10px] font-medium rounded border border-border hover:bg-muted disabled:opacity-50 text-foreground"
            >
              {probesRunning ? "Running..." : "Run Probes"}
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-3 py-2">
          {probesRunning && (
            <div className="flex items-center gap-2 py-1">
              <LoadingSpinner size={12} />
              <span className="text-[11px] text-muted-foreground">Probing storage locations...</span>
            </div>
          )}

          {!probesRunning && storageProbes.length === 0 && (
            <p className="text-[11px] text-muted-foreground">
              No probe data. Click "Run Probes" to measure storage I/O latency.
            </p>
          )}

          {!probesRunning && storageProbes.length > 0 && (
            <>
              <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted">
                  <th className="text-left px-2 py-1 border-b border-border">Location</th>
                  <th className="text-right px-2 py-1 border-b border-border">Latency</th>
                  <th className="text-right px-2 py-1 border-b border-border">Read</th>
                  <th className="text-right px-2 py-1 border-b border-border">At</th>
                </tr>
              </thead>
              <tbody>
                {storageProbes.map(p => (
                  <tr key={p.id} className="even:bg-card">
                    <td className="px-2 py-1 border-b border-border text-foreground truncate max-w-[120px]" title={p.storage_location}>
                      {p.storage_location.replace(/^.*:\/\/[^/]+\//, "")}
                    </td>
                    <td className={`px-2 py-1 border-b border-border text-right font-medium ${
                      p.probe_time_ms < 50 ? "text-status-success" : p.probe_time_ms < 150 ? "text-status-warning" : "text-status-error"
                    }`}>
                      {formatLatency(p.probe_time_ms)}
                    </td>
                    <td className="px-2 py-1 border-b border-border text-right text-muted-foreground">
                      {formatBytes(p.bytes_read)}
                    </td>
                    <td className="px-2 py-1 border-b border-border text-right text-muted-foreground">
                      {formatTime(p.measured_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[9px] text-muted-foreground mt-1.5 leading-relaxed">
              I/O latency from DuckDB to cloud storage. Factored into latency predictions. Re-run after changing deployment location.
            </p>
            </>
          )}
        </div>
      )}
    </div>

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="storage"
      />
    </>
  );
};
