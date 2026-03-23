import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { HardDrive, ChevronDown, Eye, EyeOff, RefreshCw, Trash2, CheckCircle, XCircle, AlertTriangle, ExternalLink } from "lucide-react";

const statusDot = (status: string) => {
  if (status === "accessible") return "bg-status-success";
  if (status === "inaccessible") return "bg-status-error";
  return "bg-muted-foreground/40"; // untested
};

const statusIcon = (status: string, size = 12) => {
  if (status === "accessible") return <CheckCircle size={size} className="text-status-success shrink-0" />;
  if (status === "inaccessible") return <XCircle size={size} className="text-status-error shrink-0" />;
  return <AlertTriangle size={size} className="text-muted-foreground shrink-0" />;
};

const categoryLabel = (cat: string | null) => {
  if (cat === "auth") return "Authorization";
  if (cat === "firewall") return "Firewall";
  if (cat === "vnet") return "VNet";
  if (cat === "dns") return "DNS";
  return "Unknown";
};

export const StorageAccountsManager: React.FC = () => {
  const {
    storageAccounts, azureStorageConfig, connectedWorkspace,
    reloadStorageAccounts, reloadAzureStorageConfig,
    testStorageConnectivity, storageTestRunning,
    openSpModal, setOpenSpModal,
  } = useApp();

  const [open, setOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // SP modal form state
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [saving, setSaving] = useState(false);

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

  // Summary for header
  const accessible = storageAccounts.filter(a => a.status === "accessible").length;
  const inaccessible = storageAccounts.filter(a => a.status === "inaccessible").length;
  const total = storageAccounts.length;

  const summaryDot = () => {
    if (!connectedWorkspace) return "bg-muted-foreground/40";
    if (!azureStorageConfig.configured) return "bg-muted-foreground/40";
    if (inaccessible > 0) return "bg-status-error";
    if (accessible === total && total > 0) return "bg-status-success";
    return "bg-status-warning";
  };

  const summaryText = () => {
    if (!connectedWorkspace) return "No workspace";
    if (!azureStorageConfig.configured) return "Not configured";
    if (total === 0) return "No accounts discovered";
    if (inaccessible > 0) return `${inaccessible}/${total} inaccessible`;
    return `${accessible}/${total} accessible`;
  };

  const openModal = () => {
    setTenantId(azureStorageConfig.tenant_id ?? "");
    setClientId(azureStorageConfig.client_id ?? "");
    setClientSecret("");
    setShowSecret(false);
    setOpenSpModal(true);
  };

  const handleSave = async () => {
    if (!tenantId.trim() || !clientId.trim() || !clientSecret.trim()) return;
    setSaving(true);
    try {
      await mockApi.saveAzureStorageConfig(tenantId.trim(), clientId.trim(), clientSecret.trim());
      await reloadAzureStorageConfig();
      // Auto-test after saving new credentials
      await testStorageConnectivity();
      setOpenSpModal(false);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfig = async () => {
    await mockApi.deleteAzureStorageConfig();
    await reloadAzureStorageConfig();
    await reloadStorageAccounts();
    setShowDeleteConfirm(false);
  };

  const handleTestAll = async () => {
    await testStorageConnectivity();
  };

  const handleTestOne = async (account: string) => {
    await testStorageConnectivity(account);
  };

  return (
    <div ref={wrapperRef} className="text-[12px] relative">
      {/* ── Compact header bar ── */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-1.5 flex items-center gap-2 hover:bg-muted/50 transition-colors"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${summaryDot()}`} />
        <span className="font-semibold text-foreground">Storage Accounts</span>
        <span className="text-[10px] text-muted-foreground truncate">{summaryText()}</span>
        <ChevronDown size={12} className={`ml-auto text-muted-foreground shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {/* ── Expandable dropdown ── */}
      {open && (
        <div className="border-t border-panel-border bg-background">
          {/* No workspace connected */}
          {!connectedWorkspace && (
            <div className="px-3 py-2 text-[10px] text-muted-foreground">
              Connect to a Databricks workspace to discover storage accounts from Unity Catalog.
            </div>
          )}

          {/* Workspace connected — show full UI */}
          {connectedWorkspace && (
            <>
          {/* Action bar */}
          <div className="px-3 py-1 flex items-center justify-between">
            <button
              onClick={openModal}
              className="text-[10px] text-primary hover:text-primary/80 font-medium"
            >
              {azureStorageConfig.configured ? "Edit SP" : "Configure Service Principal"}
            </button>
            <div className="flex items-center gap-2">
              {azureStorageConfig.configured && (
                <>
                  <button
                    onClick={handleTestAll}
                    disabled={storageTestRunning}
                    className="text-[10px] text-primary hover:text-primary/80 disabled:opacity-40 flex items-center gap-0.5"
                  >
                    {storageTestRunning ? <LoadingSpinner size={10} /> : <RefreshCw size={10} />}
                    Test All
                  </button>
                  <button
                    onClick={() => setShowDeleteConfirm(true)}
                    className="text-muted-foreground hover:text-status-error"
                    title="Remove service principal"
                  >
                    <Trash2 size={12} />
                  </button>
                </>
              )}
            </div>
          </div>

          {/* SP info when configured */}
          {azureStorageConfig.configured && (
            <div className="px-3 py-1 border-t border-border text-[10px] text-muted-foreground">
              <span>Tenant: <span className="font-mono text-foreground">{azureStorageConfig.tenant_id?.substring(0, 8)}...</span></span>
              <span className="ml-3">Client: <span className="font-mono text-foreground">{azureStorageConfig.client_id?.substring(0, 8)}...</span></span>
            </div>
          )}

          {/* Not configured message */}
          {!azureStorageConfig.configured && (
            <div className="px-3 py-2 border-t border-border text-[10px] text-muted-foreground">
              Configure an Azure service principal to enable DuckDB access to external Delta tables stored in Azure.
            </div>
          )}

          {/* Storage accounts list */}
          {azureStorageConfig.configured && storageAccounts.length > 0 && (
            <div className="divide-y divide-border border-t border-border">
              {storageAccounts.map(acct => (
                <div key={acct.storage_account} className="px-3 py-1.5">
                  <div className="flex items-center gap-1.5">
                    {statusIcon(acct.status)}
                    <HardDrive size={11} className="text-muted-foreground shrink-0" />
                    <span className="font-mono text-foreground truncate text-[10px]">{acct.storage_account.split(".")[0]}</span>
                    <button
                      onClick={() => handleTestOne(acct.storage_account)}
                      disabled={storageTestRunning}
                      className="ml-auto text-[9px] text-primary hover:text-primary/80 disabled:opacity-40"
                    >
                      Test
                    </button>
                  </div>
                  {acct.status === "inaccessible" && (
                    <div className="mt-0.5 pl-5">
                      <span className="text-[10px] text-status-error">{categoryLabel(acct.failure_category)}: </span>
                      <span className="text-[10px] text-muted-foreground">{acct.failure_reason}</span>
                      {acct.azure_portal_link && (
                        <a
                          href={acct.azure_portal_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-1 inline-flex items-center gap-0.5 text-[9px] text-primary hover:text-primary/80"
                        >
                          Fix in Azure Portal <ExternalLink size={8} />
                        </a>
                      )}
                    </div>
                  )}
                  {acct.tested_at && (
                    <div className="text-[9px] text-muted-foreground/60 pl-5 mt-0.5">
                      Tested: {new Date(acct.tested_at).toLocaleString()}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {azureStorageConfig.configured && storageAccounts.length === 0 && (
            <div className="px-3 py-2 border-t border-border text-[10px] text-muted-foreground">
              No storage accounts discovered. Browse the catalog to discover tables and their storage locations.
            </div>
          )}
            </>
          )}
        </div>
      )}

      {/* ── Service Principal Modal ── */}
      {openSpModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpenSpModal(false)} />
          <div className="relative bg-background border border-border rounded-lg shadow-lg p-4 w-[380px] space-y-3 z-10">
            <h3 className="text-[13px] font-semibold text-foreground">Azure Service Principal</h3>
            <p className="text-[11px] text-muted-foreground">
              Provide credentials for an Azure AD service principal with Storage Blob Data Reader access.
            </p>
            <div className="space-y-2">
              <div>
                <label className="text-[10px] font-medium text-muted-foreground">Tenant ID</label>
                <input
                  type="text"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={tenantId}
                  onChange={e => setTenantId(e.target.value)}
                  className="w-full px-2 py-1.5 border border-border rounded text-[12px] bg-background text-foreground font-mono"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground">Client ID</label>
                <input
                  type="text"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={clientId}
                  onChange={e => setClientId(e.target.value)}
                  className="w-full px-2 py-1.5 border border-border rounded text-[12px] bg-background text-foreground font-mono"
                />
              </div>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground">Client Secret</label>
                <div className="relative">
                  <input
                    type={showSecret ? "text" : "password"}
                    placeholder="Enter client secret"
                    value={clientSecret}
                    onChange={e => setClientSecret(e.target.value)}
                    className="w-full px-2 py-1.5 pr-8 border border-border rounded text-[12px] bg-background text-foreground"
                  />
                  <button
                    onClick={() => setShowSecret(prev => !prev)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                  >
                    {showSecret ? <EyeOff size={12} /> : <Eye size={12} />}
                  </button>
                </div>
              </div>
            </div>
            {azureStorageConfig.configured && (
              <p className="text-[10px] text-muted-foreground">Credentials are already configured. Saving will overwrite them.</p>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setOpenSpModal(false)} className="px-3 py-1 border border-border rounded text-[11px] text-foreground">Cancel</button>
              <button
                onClick={handleSave}
                disabled={!tenantId.trim() || !clientId.trim() || !clientSecret.trim() || saving}
                className="px-3 py-1 bg-primary text-primary-foreground rounded text-[11px] disabled:opacity-40 flex items-center gap-1"
              >
                {saving && <LoadingSpinner size={10} />}
                Save & Test
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Remove Service Principal"
        description="Remove the Azure service principal configuration? Storage account access tests will be reset."
        onConfirm={handleDeleteConfig}
        onCancel={() => setShowDeleteConfirm(false)}
        destructive
      />
    </div>
  );
};
