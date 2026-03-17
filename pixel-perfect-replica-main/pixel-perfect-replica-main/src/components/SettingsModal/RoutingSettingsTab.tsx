import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

export const RoutingSettingsTab: React.FC = () => {
  const { token } = useAuth();
  const [timeWeight, setTimeWeight] = useState(0.5);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) return;
    mockApi.getRoutingSettings(token).then(s => { setTimeWeight(s.time_weight); setLoading(false); });
  }, [token]);

  const handleSave = async () => {
    if (!token) return;
    setSaving(true);
    await mockApi.saveRoutingSettings(token, { time_weight: timeWeight, cost_weight: 1 - timeWeight });
    setSaving(false);
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  return (
    <div className="p-4 space-y-4">
      <div>
        <div className="flex justify-between text-[12px] mb-1 text-muted-foreground">
          <span>Optimize for Speed</span>
          <span>Optimize for Cost</span>
        </div>
        <input
          type="range" min="0" max="1" step="0.01" value={timeWeight}
          onChange={e => setTimeWeight(+e.target.value)}
          className="w-full"
        />
        <p className="text-[12px] text-foreground mt-1">
          Speed weight: {Math.round(timeWeight * 100)}% | Cost weight: {Math.round((1 - timeWeight) * 100)}%
        </p>
      </div>
      <button
        onClick={handleSave} disabled={saving}
        className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium"
      >
        Save
      </button>
      <p className="text-[11px] text-muted-foreground">
        These weights control how the ML model balances execution speed versus cost when choosing an engine. Only applies when a trained model is active and routing mode is set to Smart.
      </p>
    </div>
  );
};
