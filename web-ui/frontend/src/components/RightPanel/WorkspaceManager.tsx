import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Plug, Unplug, Trash2, Plus, Eye, EyeOff, Key, ChevronDown } from "lucide-react";

export const WorkspaceManager: React.FC = () => {
  const { workspaces, reloadWorkspaces, connectedWorkspace } = useApp();
  const [open, setOpen] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");

  // PAT token modal state
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [showTokenText, setShowTokenText] = useState(false);

  // Close dropdown on click outside
  const wrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const openTokenModal = (id: string) => {
    setTokenModalId(id);
    setTokenInput("");
    setShowTokenText(false);
  };

  const handleSetToken = async () => {
    if (!tokenModalId || !tokenInput.trim()) return;
    await mockApi.setWorkspaceToken(tokenModalId, tokenInput.trim());
    setTokenModalId(null);
    setTokenInput("");
    await reloadWorkspaces();
  };

  const handleConnect = async (id: string) => {
    setConnecting(id);
    try {
      await mockApi.connectWorkspace(id);
      await reloadWorkspaces();
    } catch {
      // token missing
    } finally {
      setConnecting(null);
    }
  };

  const handleDisconnect = async (id: string) => {
    await mockApi.disconnectWorkspace(id);
    await reloadWorkspaces();
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    await mockApi.deleteWorkspace(deleteId);
    await reloadWorkspaces();
    setDeleteId(null);
  };

  const handleAdd = async () => {
    if (!newName.trim() || !newUrl.trim()) return;
    await mockApi.addWorkspace(newName.trim(), newUrl.trim());
    await reloadWorkspaces();
    setNewName("");
    setNewUrl("");
    setShowAdd(false);
  };

  const tokenModalWs = tokenModalId ? workspaces.find(w => w.id === tokenModalId) : null;

  return (
    <div ref={wrapperRef} className="text-[12px] relative">
      {/* ── Compact header bar ── */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-1.5 flex items-center gap-2 hover:bg-muted/50 transition-colors"
      >
        {/* Status dot */}
        <span className={`w-2 h-2 rounded-full shrink-0 ${connectedWorkspace ? "bg-status-success" : "bg-muted-foreground/40"}`} />
        <span className="font-semibold text-foreground">Workspaces</span>
        {connectedWorkspace && (
          <span className="text-[10px] text-muted-foreground truncate">{connectedWorkspace.name}</span>
        )}
        {!connectedWorkspace && (
          <span className="text-[10px] text-muted-foreground">Not connected</span>
        )}
        <ChevronDown size={12} className={`ml-auto text-muted-foreground shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {/* ── Expandable dropdown ── */}
      {open && (
        <div className="border-t border-panel-border bg-background">
          {/* Add button */}
          <div className="px-3 py-1 flex justify-end">
            <button onClick={() => setShowAdd(!showAdd)} className="text-primary hover:text-primary/80"><Plus size={14} /></button>
          </div>

          {showAdd && (
            <div className="px-3 py-2 border-b border-border space-y-1.5">
              <input placeholder="Name" value={newName} onChange={e => setNewName(e.target.value)} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
              <input placeholder="URL (https://...)" value={newUrl} onChange={e => setNewUrl(e.target.value)} className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground" />
              <div className="flex gap-2">
                <button onClick={handleAdd} className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px]">Add</button>
                <button onClick={() => setShowAdd(false)} className="px-3 py-1 border border-border rounded text-[11px] text-foreground">Cancel</button>
              </div>
            </div>
          )}

          <div className="divide-y divide-border">
            {workspaces.map(ws => (
              <div key={ws.id} className={`px-3 py-1.5 ${ws.connected ? "bg-primary/5" : ""}`}>
                <div className="flex items-center justify-between gap-1">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-foreground truncate">{ws.name}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{ws.url}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {!ws.connected && (
                      <button
                        onClick={() => openTokenModal(ws.id)}
                        className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-muted text-muted-foreground hover:text-foreground"
                        title="Set PAT token"
                      >
                        <Key size={11} />
                      </button>
                    )}
                    {ws.connected ? (
                      <button onClick={() => handleDisconnect(ws.id)} className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-muted text-foreground" title="Disconnect">
                        <Unplug size={12} />
                      </button>
                    ) : (
                      <button
                        onClick={() => handleConnect(ws.id)}
                        disabled={!ws.token || connecting === ws.id}
                        className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-muted disabled:opacity-40 text-foreground"
                        title={ws.token ? "Connect" : "Set PAT token first"}
                      >
                        {connecting === ws.id ? <LoadingSpinner size={12} /> : <Plug size={12} />}
                      </button>
                    )}
                    <button onClick={() => setDeleteId(ws.id)} className="text-muted-foreground hover:text-status-error">
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                <div className="text-[10px] mt-0.5">
                  {ws.connected
                    ? <span className="text-status-success">Connected</span>
                    : ws.token
                      ? <span className="text-muted-foreground">Ready to connect</span>
                      : <span className="text-status-warning">No token</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* PAT Token Modal */}
      {tokenModalId && tokenModalWs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60" onClick={() => setTokenModalId(null)} />
          <div className="relative bg-background border border-border rounded-lg shadow-lg p-4 w-[340px] space-y-3 z-10">
            <h3 className="text-[13px] font-semibold text-foreground">Set PAT Token</h3>
            <p className="text-[11px] text-muted-foreground">{tokenModalWs.name}</p>
            <div className="relative">
              <input
                type={showTokenText ? "text" : "password"}
                placeholder="Enter Personal Access Token"
                value={tokenInput}
                onChange={e => setTokenInput(e.target.value)}
                className="w-full px-2 py-1.5 pr-8 border border-border rounded text-[12px] bg-background text-foreground"
                autoFocus
              />
              <button
                onClick={() => setShowTokenText(prev => !prev)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
              >
                {showTokenText ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
            </div>
            {tokenModalWs.token && (
              <p className="text-[10px] text-muted-foreground">A token is already set. Saving will overwrite it.</p>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setTokenModalId(null)} className="px-3 py-1 border border-border rounded text-[11px] text-foreground">Cancel</button>
              <button
                onClick={handleSetToken}
                disabled={!tokenInput.trim()}
                className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px] disabled:opacity-40"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteId !== null}
        title="Delete Workspace"
        description="Delete this workspace? This cannot be undone."
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        destructive
      />
    </div>
  );
};
