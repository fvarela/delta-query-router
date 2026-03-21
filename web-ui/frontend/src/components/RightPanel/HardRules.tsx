import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { RoutingRule } from "@/types";
import { Trash2, Plus, ChevronRight, ChevronDown, X, ArrowUp, ArrowDown, GitBranch, Info } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

const conditionOptions = [
  { value: "table_name", label: "Table Name" },
  { value: "table_size", label: "Data Size" },
  { value: "query_complexity", label: "Query Complexity" },
];

const comparatorOptions = [
  { value: "greater_than", label: "Greater Than" },
  { value: "less_than", label: "Less Than" },
  { value: "equals", label: "Equal To" },
];

const targetOptions = [
  { value: "duckdb", label: "DuckDB" },
  { value: "databricks", label: "Databricks" },
];

export const HardRules: React.FC = () => {
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  // New rule form
  const [newCondition, setNewCondition] = useState("table_name");
  const [newComparator, setNewComparator] = useState("equals");
  const [newValue, setNewValue] = useState("");
  const [newTarget, setNewTarget] = useState("duckdb");

  const load = async () => {
    const r = await mockApi.getRoutingRules();
    setRules(r);
  };

  useEffect(() => { load(); }, []);

  const customRules = rules.filter(r => !r.is_system).sort((a, b) => a.priority - b.priority);

  const handleDelete = async () => {
    if (deleteId === null) return;
    await mockApi.deleteRoutingRule(deleteId);
    await load();
    setDeleteId(null);
  };

  const handleAdd = async () => {
    if (!newValue.trim()) return;
    const maxPriority = Math.max(0, ...customRules.map(r => r.priority));
    await mockApi.createRoutingRule({
      priority: maxPriority + 1,
      condition_type: newCondition,
      condition_value: newComparator === "equals" ? newValue : `${newComparator}:${newValue}`,
      target_engine: newTarget,
      is_system: false,
      enabled: true,
    });
    await load();
    setShowAdd(false);
    setNewValue("");
  };

  const handleMoveUp = async (idx: number) => {
    if (idx === 0) return;
    const current = customRules[idx];
    const above = customRules[idx - 1];
    // Swap priorities
    await mockApi.updateRoutingRule(current.id, { priority: above.priority });
    await mockApi.updateRoutingRule(above.id, { priority: current.priority });
    await load();
  };

  const handleMoveDown = async (idx: number) => {
    if (idx === customRules.length - 1) return;
    const current = customRules[idx];
    const below = customRules[idx + 1];
    // Swap priorities
    await mockApi.updateRoutingRule(current.id, { priority: below.priority });
    await mockApi.updateRoutingRule(below.id, { priority: current.priority });
    await load();
  };

  const parseRule = (r: RoutingRule) => {
    const condLabel = conditionOptions.find(c => c.value === r.condition_type)?.label ?? r.condition_type;
    let comparator = "Equal To";
    let value = r.condition_value;
    if (r.condition_value.includes(":")) {
      const [op, ...rest] = r.condition_value.split(":");
      const compOption = comparatorOptions.find(c => c.value === op);
      if (compOption) {
        comparator = compOption.label;
        value = rest.join(":");
      }
    }
    const targetLabel = targetOptions.find(t => t.value === r.target_engine)?.label ?? r.target_engine;
    return { condLabel, comparator, value, targetLabel };
  };

  // Build a short summary of rules for the collapsed view
  const summary = customRules.length > 0
    ? customRules.slice(0, 2).map(r => {
        const p = parseRule(r);
        return `${p.value} \u2192 ${p.targetLabel}`;
      }).join(", ") + (customRules.length > 2 ? ", \u2026" : "")
    : null;

  return (
    <>
      {/* Collapsible section */}
      <div className="text-[12px]">
        <div
          className="w-full px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 hover:bg-muted/50"
        >
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 flex-1 min-w-0"
          >
            {expanded ? <ChevronDown size={12} className="text-muted-foreground shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground shrink-0" />}
            <GitBranch size={12} className="text-primary shrink-0" />
            <span className="font-semibold text-foreground">If-Then Rules</span>
            <span className="text-[10px] text-muted-foreground">({customRules.length})</span>
          </button>
          <button
            onClick={() => setShowInfoModal(true)}
            className="text-muted-foreground hover:text-primary transition-colors shrink-0"
            title="How If-Then Rules work"
          >
            <Info size={12} />
          </button>
        </div>
        {expanded && (
          <div className="px-3 py-2">
            {customRules.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No rules defined.</p>
            ) : (
              <div className="space-y-1">
                {customRules.map(r => {
                  const { condLabel, comparator, value, targetLabel } = parseRule(r);
                  return (
                    <div key={r.id} className="text-[11px] text-muted-foreground truncate">
                      {condLabel} {comparator} <span className="text-foreground font-medium">{value}</span> → {targetLabel}
                    </div>
                  );
                })}
              </div>
            )}
            <button
              onClick={() => setShowModal(true)}
              className="mt-2 text-[10px] text-primary hover:text-primary/80 font-medium"
            >
              Edit Rules...
            </button>
          </div>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background border border-border rounded-lg shadow-lg w-[500px] max-h-[80vh] flex flex-col text-[12px]">
            {/* Header */}
            <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
              <span className="font-semibold text-foreground text-[14px]">If-Then Rules ({customRules.length})</span>
              <button onClick={() => setShowModal(false)} className="text-muted-foreground hover:text-foreground">
                <X size={16} />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {customRules.length === 0 && !showAdd ? (
                <div className="text-[11px] text-muted-foreground py-4 text-center">No rules defined. Click "Add Rule" to create one.</div>
              ) : (
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-muted">
                      <th className="text-left px-2 py-1.5 border-b border-border">Condition</th>
                      <th className="text-left px-2 py-1.5 border-b border-border">Comparator</th>
                      <th className="text-left px-2 py-1.5 border-b border-border">Value</th>
                      <th className="text-left px-2 py-1.5 border-b border-border">Target</th>
                      <th className="w-16 px-1 py-1.5 border-b border-border"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {customRules.map((r, idx) => {
                      const { condLabel, comparator, value, targetLabel } = parseRule(r);
                      return (
                        <tr key={r.id} className="even:bg-card hover:bg-muted/50">
                          <td className="px-2 py-1.5 border-b border-border text-foreground">{condLabel}</td>
                          <td className="px-2 py-1.5 border-b border-border text-foreground">{comparator}</td>
                          <td className="px-2 py-1.5 border-b border-border text-foreground">{value}</td>
                          <td className="px-2 py-1.5 border-b border-border text-foreground">{targetLabel}</td>
                          <td className="px-1 py-1.5 border-b border-border">
                            <div className="flex items-center gap-0.5">
                              <button
                                disabled={idx === 0}
                                onClick={() => handleMoveUp(idx)}
                                className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                                title="Move up"
                              >
                                <ArrowUp size={11} />
                              </button>
                              <button
                                disabled={idx === customRules.length - 1}
                                onClick={() => handleMoveDown(idx)}
                                className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                                title="Move down"
                              >
                                <ArrowDown size={11} />
                              </button>
                              <button onClick={() => setDeleteId(r.id)} className="text-muted-foreground hover:text-status-error" title="Delete">
                                <Trash2 size={11} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}

              {/* Add form */}
              {showAdd && (
                <div className="mt-3 p-3 border border-border rounded space-y-2 bg-muted/20">
                  <div className="flex gap-2">
                    <select value={newCondition} onChange={e => setNewCondition(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                      {conditionOptions.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>
                    <select value={newComparator} onChange={e => setNewComparator(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                      {comparatorOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <input placeholder="Value" value={newValue} onChange={e => setNewValue(e.target.value)} className="flex-1 px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground" />
                    <select value={newTarget} onChange={e => setNewTarget(e.target.value)} className="px-2 py-1 border border-border rounded text-[11px] bg-background text-foreground">
                      {targetOptions.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleAdd} className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px]">Add Rule</button>
                    <button onClick={() => setShowAdd(false)} className="px-3 py-1 border border-border rounded text-[11px] text-foreground">Cancel</button>
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-4 py-3 border-t border-border flex justify-between shrink-0">
              <button
                onClick={() => setShowAdd(!showAdd)}
                className="flex items-center gap-1 px-3 py-1.5 bg-primary text-primary-foreground rounded text-[11px] font-medium"
              >
                <Plus size={12} /> Add Rule
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="px-3 py-1.5 border border-border rounded text-[11px] text-foreground"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteId !== null}
        title="Delete Rule"
        description="Delete this routing rule?"
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        destructive
      />

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="rules"
      />
    </>
  );
};
