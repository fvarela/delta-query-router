import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type { Model } from "@/types";
import { Trash2 } from "lucide-react";

export const ModelsTab: React.FC = () => {
  const { token } = useAuth();
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  useEffect(() => {
    if (!token) return;
    mockApi.getModels(token).then(m => { setModels(m); setLoading(false); });
  }, [token]);

  const handleTrain = async () => {
    if (!token) return;
    setTraining(true);
    const m = await mockApi.trainModel(token);
    setModels(prev => [...prev, m]);
    setTraining(false);
  };

  const handleActivate = async (id: number, active: boolean) => {
    if (!token) return;
    if (active) {
      await mockApi.activateModel(token, id);
    } else {
      await mockApi.deactivateModel(token, id);
    }
    const updated = await mockApi.getModels(token);
    setModels(updated);
  };

  const handleDelete = async () => {
    if (!token || deleteId === null) return;
    await mockApi.deleteModel(token, deleteId);
    setModels(prev => prev.filter(m => m.id !== deleteId));
    setDeleteId(null);
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  return (
    <div className="p-4 space-y-3">
      <button
        onClick={handleTrain} disabled={training}
        className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium flex items-center gap-2"
      >
        {training && <LoadingSpinner size={14} />}
        {training ? "Training..." : "Train New Model"}
      </button>

      <div className="space-y-2">
        {models.map(m => (
          <div key={m.id} className="border border-border rounded-md p-3 bg-card">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-semibold text-foreground">Model #{m.id}</span>
                <StatusBadge variant={m.is_active ? "success" : "inactive"}>
                  {m.is_active ? "Active" : "Inactive"}
                </StatusBadge>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleActivate(m.id, !m.is_active)}
                  className="px-2 py-0.5 border border-border rounded text-[11px] hover:bg-muted"
                >
                  {m.is_active ? "Deactivate" : "Activate"}
                </button>
                <button onClick={() => setDeleteId(m.id)} className="text-muted-foreground hover:text-status-error">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
            <div className="text-[11px] text-muted-foreground space-y-0.5">
              <p>Created: {new Date(m.created_at).toLocaleDateString()}</p>
              <p>R² Score: {m.accuracy_metrics.r_squared.toFixed(2)} | MAE: {m.accuracy_metrics.mae_ms}ms</p>
              <div className="flex gap-1 flex-wrap mt-1">
                {m.linked_engines.map(e => (
                  <span key={e} className="px-1.5 py-0.5 bg-muted rounded text-[10px]">{e}</span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      <ConfirmDialog open={deleteId !== null} title="Delete Model" description="Delete this model? This cannot be undone." onConfirm={handleDelete} onCancel={() => setDeleteId(null)} destructive />
    </div>
  );
};
