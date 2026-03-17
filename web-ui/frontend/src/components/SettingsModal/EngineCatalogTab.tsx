import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { EngineCatalogEntry } from "@/types";
import { Trash2 } from "lucide-react";

export const EngineCatalogTab: React.FC = () => {
  const { token } = useAuth();
  const [entries, setEntries] = useState<EngineCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    if (!token) return;
    mockApi.getEngineCatalog(token).then(e => { setEntries(e); setLoading(false); });
  }, [token]);

  const handleToggle = async (id: number, enabled: boolean) => {
    if (!token) return;
    const updated = await mockApi.toggleEngineCatalogEntry(token, id, enabled);
    setEntries(prev => prev.map(e => e.id === id ? updated : e));
  };

  const handleReset = async () => {
    if (!token) return;
    const res = await mockApi.resetEngineCatalog(token);
    setEntries(res);
    setConfirmReset(false);
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  const databricksEntries = entries.filter(e => e.engine_type === "databricks_sql");
  const duckdbEntries = entries.filter(e => e.engine_type === "duckdb");

  const renderSection = (title: string, items: EngineCatalogEntry[]) => (
    <div className="mb-4">
      <h3 className="text-[13px] font-semibold mb-2 text-foreground">{title}</h3>
      <table className="w-full text-[12px] border border-border">
        <thead>
          <tr className="bg-muted">
            <th className="text-left px-2 py-1.5 border-b border-border">Display Name</th>
            <th className="text-left px-2 py-1.5 border-b border-border">Config</th>
            <th className="text-center px-2 py-1.5 border-b border-border">Enabled</th>
            <th className="text-center px-2 py-1.5 border-b border-border">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map(e => (
            <tr key={e.id} className="even:bg-card">
              <td className="px-2 py-1.5 border-b border-border">{e.display_name}</td>
              <td className="px-2 py-1.5 border-b border-border text-muted-foreground">
                {e.engine_type === "duckdb"
                  ? `${e.config.memory_gb}GB RAM, ${e.config.cpu_count} CPU`
                  : `T-shirt size: ${e.config.cluster_size}`}
              </td>
              <td className="px-2 py-1.5 border-b border-border text-center">
                <input type="checkbox" checked={e.enabled} onChange={ev => handleToggle(e.id, ev.target.checked)} />
              </td>
              <td className="px-2 py-1.5 border-b border-border text-center">
                <button
                  disabled={e.is_default}
                  title={e.is_default ? "Default configs cannot be deleted" : "Delete"}
                  className="text-muted-foreground hover:text-status-error disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <Trash2 size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="p-4">
      {renderSection("Databricks Serverless Engines", databricksEntries)}
      {renderSection("DuckDB Engines", duckdbEntries)}
      <button
        onClick={() => setConfirmReset(true)}
        className="px-3 py-1.5 border border-border rounded-md text-[12px] hover:bg-muted mt-2"
      >
        Reset to Defaults
      </button>
      <ConfirmDialog
        open={confirmReset} title="Reset Engine Catalog"
        description="This will delete all custom engine configs and re-enable all defaults. Continue?"
        onConfirm={handleReset} onCancel={() => setConfirmReset(false)} destructive
      />
    </div>
  );
};
