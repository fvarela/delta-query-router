import React, { useState, useCallback } from "react";
import { HardDrive, Cloud } from "lucide-react";
import { useApp } from "@/contexts/AppContext";
import { isMockMode } from "@/lib/mockMode";
import { api } from "@/lib/api";
import type { EngineCatalogEntry } from "@/types";

const TIMEOUT_OPTIONS = [5, 15, 30, 60];

export const EnginesManagement: React.FC = () => {
  const { engines, reloadEngines } = useApp();
  const [measuring, setMeasuring] = useState<Record<string, boolean>>({});
  const mock = isMockMode();

  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb");
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql");

  const toggleActive = useCallback(async (engine: EngineCatalogEntry) => {
    if (mock) return;
    try {
      await api.put(`/api/engines/${engine.id}`, { is_active: !engine.enabled });
      await reloadEngines();
    } catch (e) {
      console.error("Failed to toggle engine:", e);
    }
  }, [mock, reloadEngines]);

  const setLifecycleMode = useCallback(async (id: string, mode: "always-on" | "on-demand") => {
    if (mock) return;
    try {
      await api.put(`/api/engines/${id}`, { lifecycle_mode: mode });
      await reloadEngines();
    } catch (e) {
      console.error("Failed to set lifecycle mode:", e);
    }
  }, [mock, reloadEngines]);

  const setIdleTimeout = useCallback(async (id: string, minutes: number) => {
    if (mock) return;
    try {
      await api.put(`/api/engines/${id}`, { idle_timeout_minutes: minutes });
      await reloadEngines();
    } catch (e) {
      console.error("Failed to set idle timeout:", e);
    }
  }, [mock, reloadEngines]);

  const measureColdStart = useCallback(async (id: string) => {
    setMeasuring(prev => ({ ...prev, [id]: true }));
    try {
      if (mock) {
        // Simulate measurement
        await new Promise(r => setTimeout(r, 2000));
      } else {
        await api.post(`/api/engines/${id}/measure-cold-start`, {});
        // Poll until measurement completes (measuring: false with a result)
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 3000));
          const data = await api.get<{ cold_start_ms: number | null; measuring?: boolean }>(`/api/engines/${id}/cold-start`);
          if (data?.measuring === false && data?.cold_start_ms != null) break;
        }
      }
      await reloadEngines();
    } catch (e) {
      console.error("Cold start measurement failed:", e);
    } finally {
      setMeasuring(prev => ({ ...prev, [id]: false }));
    }
  }, [mock, reloadEngines]);

  const startEngine = useCallback(async (id: string) => {
    if (mock) return;
    try {
      await api.post(`/api/engines/${id}/start`, {});
      await reloadEngines();
    } catch (e) {
      console.error("Failed to start engine:", e);
    }
  }, [mock, reloadEngines]);

  const stopEngine = useCallback(async (id: string) => {
    if (mock) return;
    try {
      await api.post(`/api/engines/${id}/stop`, {});
      await reloadEngines();
    } catch (e) {
      console.error("Failed to stop engine:", e);
    }
  }, [mock, reloadEngines]);

  return (
    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4">
      {/* DuckDB Section */}
      <section>
        <div className="flex items-center gap-1.5 mb-2">
          <HardDrive size={13} strokeWidth={1.5} className="text-emerald-600" />
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">DuckDB Engines</span>
        </div>
        <div className="space-y-2">
          {duckdbEngines.map(eng => {
            const lifecycleMode = eng.lifecycle_mode ?? "always-on";
            const idleTimeout = eng.idle_timeout_minutes ?? 15;
            const coldStartMs = eng.cold_start_ms;
            return (
              <div key={eng.id} className="border border-border rounded px-2.5 py-2 space-y-1.5">
                {/* Row 1: Name, specs, state, toggle */}
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${eng.runtime_state === "running" ? "bg-emerald-500" : "bg-gray-300"}`} />
                  <span className="text-[12px] font-medium text-foreground">{eng.display_name}</span>
                  <span className="text-[10px] text-muted-foreground">{eng.config.memory_gb}GB / {eng.config.cpu_count}CPU</span>
                  {/* Start/Stop button for on-demand engines */}
                  {lifecycleMode === "on-demand" && eng.enabled && (
                    <button
                      onClick={() => eng.runtime_state === "running" ? stopEngine(eng.id) : startEngine(eng.id)}
                      className="text-[9px] px-1.5 py-0.5 border border-border rounded hover:bg-muted transition-colors"
                    >
                      {eng.runtime_state === "running" ? "Stop" : "Start"}
                    </button>
                  )}
                  <span className={`text-[10px] ml-auto mr-2 ${eng.enabled ? "text-emerald-600" : "text-gray-400"}`}>
                    {eng.enabled ? "Enabled" : "Disabled"}
                  </span>
                  <button
                    onClick={() => toggleActive(eng)}
                    className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors shrink-0 ${eng.enabled ? "bg-primary" : "bg-gray-300"}`}
                    title={eng.enabled ? "Enabled" : "Disabled"}
                  >
                    <span className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${eng.enabled ? "translate-x-3.5" : "translate-x-0.5"}`} />
                  </button>
                </div>

                {/* Row 2: Lifecycle + Idle timeout + Cold start */}
                <div className="flex items-center gap-3 flex-wrap">
                  {/* Lifecycle */}
                  <div className="inline-flex rounded-md border border-border overflow-hidden">
                    <button
                      onClick={() => setLifecycleMode(eng.id, "always-on")}
                      disabled={!eng.enabled}
                      className={`px-2 py-0.5 text-[10px] font-medium transition-colors ${lifecycleMode === "always-on" ? "bg-primary text-primary-foreground" : "bg-background text-muted-foreground hover:bg-muted"} disabled:opacity-40`}
                    >
                      Always On
                    </button>
                    <button
                      onClick={() => setLifecycleMode(eng.id, "on-demand")}
                      disabled={!eng.enabled}
                      className={`px-2 py-0.5 text-[10px] font-medium transition-colors border-l border-border ${lifecycleMode === "on-demand" ? "bg-primary text-primary-foreground" : "bg-background text-muted-foreground hover:bg-muted"} disabled:opacity-40`}
                    >
                      On Demand
                    </button>
                  </div>

                  {/* Idle timeout */}
                  {lifecycleMode === "on-demand" && (
                    <select
                      value={idleTimeout}
                      onChange={e => setIdleTimeout(eng.id, Number(e.target.value))}
                      disabled={!eng.enabled}
                      className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background text-foreground disabled:opacity-40"
                    >
                      {TIMEOUT_OPTIONS.map(v => <option key={v} value={v}>{v} min idle</option>)}
                    </select>
                  )}

                  {/* Cold start */}
                  <div className="flex items-center gap-1.5 ml-auto">
                    <span className="text-[10px] text-muted-foreground">Cold start:</span>
                    <span className="text-[11px] font-mono text-foreground">
                      {lifecycleMode === "always-on" ? "0ms" : coldStartMs != null ? `${(coldStartMs / 1000).toFixed(1)}s` : "—"}
                    </span>
                    {lifecycleMode === "on-demand" && (
                      <button
                        onClick={() => measureColdStart(eng.id)}
                        disabled={measuring[eng.id] || !eng.enabled}
                        className="px-1.5 py-0.5 text-[9px] font-medium border border-border rounded hover:bg-muted transition-colors disabled:opacity-40"
                      >
                        {measuring[eng.id] ? "..." : "Measure"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Databricks Section */}
      <section>
        <div className="flex items-center gap-1.5 mb-2">
          <Cloud size={13} strokeWidth={1.5} className="text-blue-600" />
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Databricks Engines</span>
        </div>
        <div className="space-y-2">
          {databricksEngines.map(eng => {
            const coldStartMs = eng.cold_start_ms;
            return (
              <div key={eng.id} className="border border-border rounded px-2.5 py-2 space-y-1.5">
                {/* Row 1: Name, size, state, toggle */}
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${eng.runtime_state === "running" ? "bg-emerald-500" : eng.runtime_state === "starting" ? "bg-amber-400" : "bg-gray-300"}`} />
                  <span className="text-[12px] font-medium text-foreground">{eng.display_name}</span>
                  <span className="text-[10px] text-muted-foreground">{eng.config.cluster_size}</span>
                  <span className={`text-[10px] ml-auto mr-2 ${eng.enabled ? "text-emerald-600" : "text-gray-400"}`}>
                    {eng.enabled ? "Enabled" : "Disabled"}
                  </span>
                  <button
                    onClick={() => toggleActive(eng)}
                    className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors shrink-0 ${eng.enabled ? "bg-primary" : "bg-gray-300"}`}
                    title={eng.enabled ? "Enabled" : "Disabled"}
                  >
                    <span className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${eng.enabled ? "translate-x-3.5" : "translate-x-0.5"}`} />
                  </button>
                </div>

                {/* Row 2: Cold start */}
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-1.5 ml-auto">
                    <span className="text-[10px] text-muted-foreground">Cold start:</span>
                    <span className="text-[11px] font-mono text-foreground">
                      {coldStartMs != null ? `${(coldStartMs / 1000).toFixed(1)}s` : "—"}
                    </span>
                    <button
                      onClick={() => measureColdStart(eng.id)}
                      disabled={measuring[eng.id] || !eng.enabled}
                      className="px-1.5 py-0.5 text-[9px] font-medium border border-border rounded hover:bg-muted transition-colors disabled:opacity-40"
                    >
                      {measuring[eng.id] ? "..." : "Measure"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
};
