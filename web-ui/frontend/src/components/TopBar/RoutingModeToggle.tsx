import React from "react";
import { useApp } from "@/contexts/AppContext";
import type { RoutingMode } from "@/types";

const modes: { value: RoutingMode; label: string }[] = [
  { value: "duckdb", label: "DuckDB" },
  { value: "smart", label: "Smart" },
  { value: "databricks", label: "Databricks" },
];

export const RoutingModeToggle: React.FC = () => {
  const { routingMode, setRoutingMode } = useApp();

  return (
    <div className="flex items-center border border-border rounded-md overflow-hidden">
      {modes.map(m => (
        <button
          key={m.value}
          onClick={() => setRoutingMode(m.value)}
          className={`px-3 py-1 text-[12px] font-medium transition-colors ${
            routingMode === m.value
              ? "bg-primary text-primary-foreground"
              : "bg-background text-foreground hover:bg-muted"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
};
