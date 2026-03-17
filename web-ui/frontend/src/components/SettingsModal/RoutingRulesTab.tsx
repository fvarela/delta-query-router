import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { RoutingRule } from "@/types";
import { Lock, Trash2, Edit2 } from "lucide-react";

export const RoutingRulesTab: React.FC = () => {
  const { token } = useAuth();
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [newRule, setNewRule] = useState({ priority: 20, condition_type: "table_name", condition_value: "", target_engine: "duckdb" });

  useEffect(() => {
    if (!token) return;
    mockApi.getRoutingRules(token).then(r => { setRules(r); setLoading(false); });
  }, [token]);

  const handleToggle = async (id: number, enabled: boolean) => {
    if (!token) return;
    const updated = await mockApi.toggleRoutingRule(token, id, enabled);
    setRules(prev => prev.map(r => r.id === id ? updated : r));
  };

  const handleAdd = async () => {
    if (!token || !newRule.condition_value) return;
    const created = await mockApi.createRoutingRule(token, { ...newRule, is_system: false, enabled: true });
    setRules(prev => [...prev, created]);
    setShowAdd(false);
    setNewRule({ priority: 20, condition_type: "table_name", condition_value: "", target_engine: "duckdb" });
  };

  const handleDelete = async () => {
    if (!token || deleteId === null) return;
    await mockApi.deleteRoutingRule(token, deleteId);
    setRules(prev => prev.filter(r => r.id !== deleteId));
    setDeleteId(null);
  };

  const handleReset = async () => {
    if (!token) return;
    const res = await mockApi.resetRoutingRules(token);
    setRules(res);
    setConfirmReset(false);
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  return (
    <div className="p-4">
      <table className="w-full text-[12px] border border-border mb-3">
        <thead>
          <tr className="bg-muted">
            <th className="text-left px-2 py-1.5 border-b border-border">Priority</th>
            <th className="text-left px-2 py-1.5 border-b border-border">Condition</th>
            <th className="text-left px-2 py-1.5 border-b border-border">Value</th>
            <th className="text-left px-2 py-1.5 border-b border-border">Target</th>
            <th className="text-center px-2 py-1.5 border-b border-border">System</th>
            <th className="text-center px-2 py-1.5 border-b border-border">Enabled</th>
            <th className="text-center px-2 py-1.5 border-b border-border">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rules.sort((a, b) => a.priority - b.priority).map(r => (
            <tr key={r.id} className="even:bg-card">
              <td className="px-2 py-1.5 border-b border-border">{r.priority}</td>
              <td className="px-2 py-1.5 border-b border-border">{r.condition_type}</td>
              <td className="px-2 py-1.5 border-b border-border">{r.condition_value}</td>
              <td className="px-2 py-1.5 border-b border-border">{r.target_engine}</td>
              <td className="px-2 py-1.5 border-b border-border text-center">
                {r.is_system && <Lock size={12} className="inline text-muted-foreground" />}
              </td>
              <td className="px-2 py-1.5 border-b border-border text-center">
                <input type="checkbox" checked={r.enabled} onChange={e => handleToggle(r.id, e.target.checked)} />
              </td>
              <td className="px-2 py-1.5 border-b border-border text-center">
                <div className="flex items-center justify-center gap-1">
                  <button disabled={r.is_system} title={r.is_system ? "System rules cannot be modified" : "Edit"} className="disabled:opacity-30 disabled:cursor-not-allowed">
                    <Edit2 size={12} />
                  </button>
                  <button disabled={r.is_system} title={r.is_system ? "System rules cannot be modified" : "Delete"} onClick={() => !r.is_system && setDeleteId(r.id)} className="disabled:opacity-30 disabled:cursor-not-allowed hover:text-status-error">
                    <Trash2 size={12} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {showAdd && (
        <div className="border border-border rounded-md p-3 mb-3 space-y-2 bg-card">
          <div className="grid grid-cols-4 gap-2">
            <div>
              <label className="text-[11px] font-medium">Priority</label>
              <input type="number" value={newRule.priority} onChange={e => setNewRule(p => ({ ...p, priority: +e.target.value }))} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
            </div>
            <div>
              <label className="text-[11px] font-medium">Condition Type</label>
              <select value={newRule.condition_type} onChange={e => setNewRule(p => ({ ...p, condition_type: e.target.value }))} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground">
                {["table_type", "has_governance", "table_name", "query_complexity", "data_size"].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-medium">Value</label>
              <input type="text" value={newRule.condition_value} onChange={e => setNewRule(p => ({ ...p, condition_value: e.target.value }))} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
            </div>
            <div>
              <label className="text-[11px] font-medium">Target Engine</label>
              <select value={newRule.target_engine} onChange={e => setNewRule(p => ({ ...p, target_engine: e.target.value }))} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground">
                <option value="duckdb">duckdb</option>
                <option value="databricks">databricks</option>
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleAdd} className="px-3 py-1 bg-primary text-primary-foreground rounded text-[12px]">Save</button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1 border border-border rounded text-[12px]">Cancel</button>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <button onClick={() => setShowAdd(true)} className="px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium">Add Rule</button>
        <button onClick={() => setConfirmReset(true)} className="px-3 py-1.5 border border-border rounded-md text-[12px] hover:bg-muted">Reset Rules</button>
      </div>

      <ConfirmDialog open={deleteId !== null} title="Delete Rule" description="Delete this routing rule?" onConfirm={handleDelete} onCancel={() => setDeleteId(null)} destructive />
      <ConfirmDialog open={confirmReset} title="Reset Rules" description="This will delete all user-defined rules and restore system defaults. Continue?" onConfirm={handleReset} onCancel={() => setConfirmReset(false)} destructive />
    </div>
  );
};
