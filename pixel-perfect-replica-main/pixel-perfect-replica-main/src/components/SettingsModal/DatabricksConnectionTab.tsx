import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useAuth, useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { CheckCircle } from "lucide-react";

export const DatabricksConnectionTab: React.FC = () => {
  const { token } = useAuth();
  const { setDatabricksConfigured } = useApp();
  const [loading, setLoading] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [host, setHost] = useState("");
  const [pat, setPat] = useState("");
  const [connectedHost, setConnectedHost] = useState("");
  const [connectedUser, setConnectedUser] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) return;
    mockApi.getDatabricksSettings(token).then(s => {
      setConfigured(s.configured);
      if (s.configured) {
        setConnectedHost(s.host || "");
        setConnectedUser(s.username || "");
      }
      setLoading(false);
    });
  }, [token]);

  const handleConnect = async () => {
    if (!token || !host || !pat) return;
    setSaving(true);
    const res = await mockApi.saveDatabricksSettings(token, { host, token: pat });
    setConfigured(true);
    setConnectedHost(res.host);
    setConnectedUser(res.username);
    setDatabricksConfigured(true);
    setSaving(false);
  };

  const handleReconfigure = () => {
    setConfigured(false);
    setHost("");
    setPat("");
  };

  if (loading) return <div className="p-4"><LoadingSpinner /></div>;

  if (configured) {
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-2 text-status-success">
          <CheckCircle size={16} />
          <span className="font-medium text-[13px]">Connected as {connectedUser}</span>
        </div>
        <p className="text-[12px] text-muted-foreground">{connectedHost}</p>
        <button onClick={handleReconfigure} className="px-3 py-1.5 border border-border rounded-md text-[12px] hover:bg-muted">
          Reconfigure
        </button>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      <div>
        <label className="block text-[12px] font-medium mb-1">Workspace URL</label>
        <input
          type="text" value={host} onChange={e => setHost(e.target.value)}
          placeholder="https://adb-1234567890.12.azuredatabricks.net"
          className="w-full px-3 py-1.5 border border-border rounded-md text-[13px] bg-background text-foreground"
        />
      </div>
      <div>
        <label className="block text-[12px] font-medium mb-1">Personal Access Token</label>
        <input
          type="password" value={pat} onChange={e => setPat(e.target.value)}
          placeholder="dapi..."
          className="w-full px-3 py-1.5 border border-border rounded-md text-[13px] bg-background text-foreground"
        />
      </div>
      <button
        onClick={handleConnect} disabled={saving || !host || !pat}
        className="px-4 py-1.5 bg-primary text-primary-foreground rounded-md text-[12px] font-medium flex items-center gap-2 disabled:opacity-50"
      >
        {saving && <LoadingSpinner size={14} />}
        Connect
      </button>
    </div>
  );
};
