import React, { useEffect, useState } from "react";
import { mockApi } from "@/mocks/api";
import type { HealthStatus } from "@/types";

const services = [
  { key: "web_ui", label: "Web UI" },
  { key: "routing_service", label: "Routing Service" },
  { key: "postgresql", label: "PostgreSQL" },
  { key: "duckdb_worker", label: "DuckDB Worker" },
  { key: "databricks", label: "Databricks" },
] as const;

const dotColor: Record<string, string> = {
  connected: "bg-status-success",
  error: "bg-status-error",
  not_configured: "bg-status-inactive",
  unknown: "bg-status-warning",
};

const statusLabel: Record<string, string> = {
  connected: "Connected",
  error: "Error",
  not_configured: "Not Configured",
  unknown: "Unknown",
};

export const HealthIndicators: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    const poll = () => mockApi.getHealthServices().then(setHealth);
    poll();
    const id = setInterval(poll, 15000);
    return () => clearInterval(id);
  }, []);

  if (!health) return null;

  return (
    <div className="flex items-center gap-4">
      {services.map(s => {
        const status = health[s.key].status;
        return (
          <div key={s.key} className="flex items-center gap-1.5">
            <div className={`w-2.5 h-2.5 rounded-full ${dotColor[status] || dotColor.unknown}`} />
            <span className="font-semibold text-foreground text-[12px]">{s.label}</span>
            <span className="text-muted-foreground text-[11px]">{statusLabel[status] || status}</span>
          </div>
        );
      })}
    </div>
  );
};
