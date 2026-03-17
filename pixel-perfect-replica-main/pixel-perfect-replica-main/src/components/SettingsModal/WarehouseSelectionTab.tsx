import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth, useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import type { Warehouse } from "@/types";

export const WarehouseSelectionTab: React.FC = () => {
  const { token } = useAuth();
  const { isDatabricksConfigured } = useApp();
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!token || !isDatabricksConfigured) { setLoading(false); return; }
    Promise.all([
      mockApi.getWarehouses(token),
      mockApi.getDatabricksSettings(token),
    ]).then(([wh, settings]) => {
      setWarehouses(wh);
      if (settings.warehouse_id) setSelected(settings.warehouse_id);
      setLoading(false);
    });
  }, [token, isDatabricksConfigured]);

  if (!isDatabricksConfigured) {
    return <div className="p-4 text-muted-foreground text-[13px]">Connect to Databricks first on the Databricks Connection tab.</div>;
  }
  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  const handleSave = async () => {
    if (!token || !selected) return;
    setSaving(true);
    await mockApi.saveWarehouse(token, selected);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="p-4 space-y-3">
      <label className="block text-[12px] font-medium mb-1">Select Warehouse</label>
      <select
        value={selected} onChange={e => setSelected(e.target.value)}
        className="w-full px-3 py-1.5 border border-border rounded-md text-[13px] bg-background text-foreground"
      >
        <option value="">Select...</option>
        {warehouses.map(w => (
          <option key={w.id} value={w.id}>
            {w.name} ({w.state})
          </option>
        ))}
      </select>
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave} disabled={saving || !selected}
          className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium disabled:opacity-50"
        >
          Save
        </button>
        {saved && <span className="text-status-success text-[12px]">Warehouse saved</span>}
      </div>
    </div>
  );
};
