import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ArrowUp, ArrowDown, GripVertical } from "lucide-react";
import type { EnginePreference } from "@/types";

export const EnginePreferencesTab: React.FC = () => {
  const { token } = useAuth();
  const [prefs, setPrefs] = useState<EnginePreference[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) return;
    mockApi.getEnginePreferences(token).then(p => { setPrefs(p); setLoading(false); });
  }, [token]);

  const move = (index: number, dir: -1 | 1) => {
    const next = [...prefs];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    next.forEach((p, i) => p.preference_order = i + 1);
    setPrefs(next);
  };

  const handleSave = async () => {
    if (!token) return;
    setSaving(true);
    await mockApi.saveEnginePreferences(token, prefs);
    setSaving(false);
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  return (
    <div className="p-4 space-y-3">
      <div className="space-y-1">
        {prefs.map((p, i) => (
          <div key={p.engine_id} className="flex items-center gap-2 px-2 py-1.5 border border-border rounded-md bg-background">
            <GripVertical size={14} className="text-muted-foreground" />
            <span className="text-[12px] font-medium text-muted-foreground w-6">#{p.preference_order}</span>
            <span className="text-[13px] flex-1 text-foreground">{p.display_name}</span>
            <StatusBadge variant={p.engine_type === "duckdb" ? "success" : "info"}>
              {p.engine_type === "duckdb" ? "DuckDB" : "Databricks"}
            </StatusBadge>
            <button onClick={() => move(i, -1)} disabled={i === 0} className="disabled:opacity-30"><ArrowUp size={14} /></button>
            <button onClick={() => move(i, 1)} disabled={i === prefs.length - 1} className="disabled:opacity-30"><ArrowDown size={14} /></button>
          </div>
        ))}
      </div>
      <button
        onClick={handleSave} disabled={saving}
        className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium"
      >
        Save Order
      </button>
    </div>
  );
};
