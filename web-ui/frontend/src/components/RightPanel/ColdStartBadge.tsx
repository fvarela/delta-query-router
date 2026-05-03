import React, { useState, useEffect, useCallback } from "react";
import { Loader2, Thermometer } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";
import type { ColdStartMeasurement } from "@/types";

interface ColdStartBadgeProps {
  engineId: string;
  compact?: boolean; // When true, only show value (no button)
}

/**
 * Self-contained cold start badge for an engine.
 * Fetches its own data, shows value + age, provides Measure button.
 */
export const ColdStartBadge: React.FC<ColdStartBadgeProps> = ({ engineId, compact = false }) => {
  const isDuckDB = engineId.startsWith("duckdb");
  const [data, setData] = useState<ColdStartMeasurement | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [loading, setLoading] = useState(true);
  const mock = isMockMode();

  const fetchColdStart = useCallback(async () => {
    if (mock) {
      setData({ engine_id: engineId, cold_start_ms: isDuckDB ? 0 : 3200, measured_at: new Date().toISOString(), measuring: false });
      setLoading(false);
      return;
    }
    try {
      const result = await api.get<ColdStartMeasurement>(`/api/engines/${engineId}/cold-start`);
      setData(result);
      setMeasuring(result.measuring);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setData(null);
      }
    } finally {
      setLoading(false);
    }
  }, [engineId, mock, isDuckDB]);

  useEffect(() => {
    fetchColdStart();
  }, [fetchColdStart]);

  // Poll while measuring
  useEffect(() => {
    if (!measuring) return;
    const interval = setInterval(async () => {
      try {
        const result = await api.get<ColdStartMeasurement>(`/api/engines/${engineId}/cold-start`);
        setData(result);
        if (!result.measuring) {
          setMeasuring(false);
        }
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [measuring, engineId]);

  const handleMeasure = async () => {
    if (mock) {
      setMeasuring(true);
      setTimeout(() => {
        setData({ engine_id: engineId, cold_start_ms: Math.random() * 5000, measured_at: new Date().toISOString(), measuring: false });
        setMeasuring(false);
      }, 2000);
      return;
    }
    try {
      await api.post(`/api/engines/${engineId}/measure-cold-start`);
      setMeasuring(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setMeasuring(true); // Already measuring
      }
    }
  };

  if (loading) return null;

  const formatMs = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;

  const formatAge = (isoDate: string) => {
    const diff = Date.now() - new Date(isoDate).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return "today";
    if (days === 1) return "1d ago";
    return `${days}d ago`;
  };

  const isStale = data ? (Date.now() - new Date(data.measured_at).getTime()) > 7 * 86400000 : false;

  if (compact) {
    if (isDuckDB) return <span className="text-[10px] text-emerald-600">0ms</span>;
    if (!data) return <span className="text-[10px] text-muted-foreground/60 italic">no cold start</span>;
    return (
      <span className={`text-[10px] ${isStale ? "text-amber-600" : "text-muted-foreground"}`}>
        {formatMs(data.cold_start_ms)}
      </span>
    );
  }

  // DuckDB: always-on, no measurement needed
  if (isDuckDB) {
    return (
      <div className="flex items-center gap-1.5">
        <Thermometer size={9} className="text-emerald-500" />
        <span className="text-[10px] font-medium text-emerald-600">Always on</span>
        <span className="text-[9px] text-muted-foreground/50">0ms</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      {measuring ? (
        <span className="flex items-center gap-1 text-[10px] text-primary">
          <Loader2 size={9} className="animate-spin" />
          <span>Measuring...</span>
        </span>
      ) : data ? (
        <>
          <Thermometer size={9} className={isStale ? "text-amber-500" : "text-muted-foreground/60"} />
          <span className={`text-[10px] font-medium ${isStale ? "text-amber-600" : "text-foreground"}`}>
            {formatMs(data.cold_start_ms)}
          </span>
          <span className={`text-[9px] ${isStale ? "text-amber-500" : "text-muted-foreground/50"}`}>
            {formatAge(data.measured_at)}
          </span>
          <button
            onClick={handleMeasure}
            className="text-[9px] text-primary/60 hover:text-primary transition-colors ml-0.5"
            title="Re-measure cold start"
          >
            re-measure
          </button>
        </>
      ) : (
        <button
          onClick={handleMeasure}
          className="flex items-center gap-1 text-[10px] text-primary hover:text-primary/80 transition-colors"
          title="Measure cold start time for this engine"
        >
          <Thermometer size={9} />
          Measure cold start
        </button>
      )}
    </div>
  );
};
