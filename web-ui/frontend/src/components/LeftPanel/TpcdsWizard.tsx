import React, { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import type {
  TpcdsPreFlight,
  TpcdsCreateResponse,
  TpcdsCatalog,
  TpcdsStatusResponse,
} from "@/types";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  X,
  Trash2,
  Database,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  HardDrive,
  Clock,
  DollarSign,
  Info,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Scale factor metadata
// ---------------------------------------------------------------------------

interface SfMeta {
  label: string;
  size: string;
  time: string;
  cost: string;
  method: string;
}

const SF_META: Record<number, SfMeta> = {
  1: { label: "SF1", size: "~1 GB", time: "~2-5 min", cost: "Minimal (existing warehouse)", method: "CTAS from samples" },
  10: { label: "SF10", size: "~10 GB", time: "~10-15 min", cost: "~$2-5 (Databricks Job)", method: "DuckDB dsdgen Job" },
  100: { label: "SF100", size: "~100 GB", time: "~30-60 min", cost: "~$10-20 (Databricks Job)", method: "DuckDB dsdgen Job" },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const TpcdsWizard: React.FC = () => {
  // Wizard step: "list" | "info" | "config" | "running" | "done"
  const [step, setStep] = useState<"list" | "info" | "config" | "running" | "done">("list");

  // Preflight
  const [preflight, setPreflight] = useState<TpcdsPreFlight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  // Config
  const [catalogName, setCatalogName] = useState("delta_router_tpcds");
  const [scaleFactor, setScaleFactor] = useState<number>(1);
  const schemaName = `sf${scaleFactor}`;

  // Existing catalogs (for validation + management)
  const [catalogs, setCatalogs] = useState<TpcdsCatalog[]>([]);
  const [catalogsLoading, setCatalogsLoading] = useState(false);

  // Running state
  const [createResponse, setCreateResponse] = useState<TpcdsCreateResponse | null>(null);
  const [status, setStatus] = useState<TpcdsStatusResponse | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Delete confirmation
  const [deleteCatalog, setDeleteCatalog] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadCatalogs = useCallback(async () => {
    setCatalogsLoading(true);
    try {
      const list = await api.get<TpcdsCatalog[]>("/api/tpcds/catalogs");
      setCatalogs(list);
    } catch {
      setCatalogs([]);
    }
    setCatalogsLoading(false);
  }, []);

  useEffect(() => {
    loadCatalogs();
  }, [loadCatalogs]);

  const loadPreflight = async () => {
    setPreflightLoading(true);
    setPreflightError(null);
    try {
      const pf = await api.get<TpcdsPreFlight>("/api/tpcds/preflight");
      setPreflight(pf);
    } catch (err) {
      setPreflightError(err instanceof Error ? err.message : "Preflight check failed");
    }
    setPreflightLoading(false);
  };

  // ---------------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------------

  const startPolling = (id: number) => {
    const interval = setInterval(async () => {
      try {
        const s = await api.get<TpcdsStatusResponse>(`/api/tpcds/status/${id}`);
        setStatus(s);
        if (s.status === "ready" || s.status === "failed") {
          clearInterval(interval);
          pollRef.current = null;
          setStep("done");
        }
      } catch {
        // keep polling
      }
    }, 3000);
    pollRef.current = interval;
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleStartWizard = async () => {
    await loadPreflight();
    setStep("info");
  };

  const handleCreate = async () => {
    setCreateError(null);
    setStep("running");
    try {
      const resp = await api.post<TpcdsCreateResponse>("/api/tpcds/create", {
        catalog_name: catalogName,
        schema_name: schemaName,
        scale_factor: scaleFactor,
      });
      setCreateResponse(resp);
      setStatus({
        id: resp.id,
        catalog_name: resp.catalog_name,
        schema_name: resp.schema_name,
        scale_factor: resp.scale_factor,
        status: "creating",
        tables_created: 0,
        total_tables: 25,
        error_message: null,
        job_run_id: resp.job_run_id ?? null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      startPolling(resp.id);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Creation failed");
      setStep("config");
    }
  };

  const handleDelete = async () => {
    if (!deleteCatalog) return;
    setDeleteLoading(true);
    try {
      await api.del(`/api/tpcds/catalogs/${deleteCatalog}`);
      await loadCatalogs();
    } catch {
      // error shown via catalog status
    }
    setDeleteLoading(false);
    setDeleteCatalog(null);
  };

  const handleReset = () => {
    setStep("list");
    setCreateResponse(null);
    setStatus(null);
    setCreateError(null);
    setCatalogName("delta_router_tpcds");
    setScaleFactor(1);
    loadCatalogs();
  };

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const canProceedToConfig = preflight != null
    && preflight.metastore_external_access
    && preflight.warehouse_configured;

  const catalogNameExists = catalogs.some(c => c.catalog_name === catalogName);
  const catalogNameValid = /^[a-z][a-z0-9_]*$/.test(catalogName) && catalogName.length >= 2;
  const canCreate = catalogNameValid && !catalogNameExists;

  // ---------------------------------------------------------------------------
  // Render: Catalog list view (default)
  // ---------------------------------------------------------------------------

  if (step === "list") {
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5">
          <Database size={14} className="text-primary" />
          <span className="font-semibold text-foreground flex-1">TPC-DS Data</span>
        </div>

        <div className="px-3 py-2 text-[10px] text-muted-foreground border-b border-border">
          Create standardized TPC-DS benchmark tables in your workspace. Tables are created as managed Delta tables in a dedicated catalog.
        </div>

        <div className="px-3 py-2">
          <button
            onClick={handleStartWizard}
            className="w-full px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[11px] font-medium"
          >
            Set Up TPC-DS Data
          </button>
        </div>

        {/* Existing catalogs */}
        {catalogsLoading ? (
          <div className="px-3 py-2"><LoadingSpinner size={14} /></div>
        ) : catalogs.length > 0 && (
          <div className="flex-1 overflow-y-auto border-t border-border">
            <div className="px-3 py-1.5 text-[10px] text-muted-foreground font-medium">Created Catalogs</div>
            {catalogs.map(cat => (
              <div key={cat.id} className="px-3 py-1.5 border-b border-border flex items-center gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground truncate">{cat.catalog_name}</span>
                    <StatusBadge variant={
                      cat.status === "ready" ? "success"
                        : cat.status === "failed" ? "error"
                          : cat.status === "creating" ? "warning"
                            : "inactive"
                    }>
                      {cat.status}
                    </StatusBadge>
                  </div>
                  <div className="text-[10px] text-muted-foreground flex items-center gap-2 mt-0.5">
                    <span>SF{cat.scale_factor}</span>
                    <span>{cat.tables_created}/{cat.total_tables} tables</span>
                    {cat.created_at && <span>{new Date(cat.created_at).toLocaleDateString()}</span>}
                  </div>
                  {cat.error_message && (
                    <div className="text-[10px] text-status-error mt-0.5 truncate" title={cat.error_message}>
                      {cat.error_message}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setDeleteCatalog(cat.catalog_name)}
                  className="text-muted-foreground hover:text-status-error shrink-0"
                  title="Delete catalog"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}

        <ConfirmDialog
          open={deleteCatalog !== null}
          title="Delete TPC-DS Data"
          description={`This will permanently delete all TPC-DS data in catalog "${deleteCatalog}". All tables and schemas will be removed from your workspace. This cannot be undone.`}
          onConfirm={handleDelete}
          onCancel={() => setDeleteCatalog(null)}
          destructive
        />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Step 1 — Information / Preflight
  // ---------------------------------------------------------------------------

  if (step === "info") {
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
          <button onClick={handleReset}><ArrowLeft size={14} /></button>
          <span className="font-semibold text-foreground">TPC-DS Setup</span>
          <span className="text-[10px] text-muted-foreground ml-auto">Step 1 of 2</span>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {/* What gets created */}
          <div>
            <h4 className="font-semibold text-foreground mb-1 flex items-center gap-1">
              <Info size={12} className="text-primary" />
              What gets created
            </h4>
            <p className="text-[11px] text-muted-foreground">
              A new Unity Catalog catalog with one schema containing all 25 standard TPC-DS tables as managed Delta tables.
              EXTERNAL USE SCHEMA is granted automatically so DuckDB can read the data.
            </p>
          </div>

          {/* Prerequisites */}
          <div>
            <h4 className="font-semibold text-foreground mb-1">Prerequisites</h4>
            {preflightLoading ? (
              <LoadingSpinner size={14} />
            ) : preflightError ? (
              <div className="text-[11px] text-status-error">{preflightError}</div>
            ) : preflight ? (
              <div className="space-y-1 text-[11px]">
                <PrereqRow ok={preflight.metastore_external_access} label="Metastore external access enabled" />
                <PrereqRow ok={preflight.warehouse_configured} label="SQL Warehouse configured" />
                <PrereqRow ok={true} label="Workspace connected" />
              </div>
            ) : null}
          </div>

          {/* Scale factor comparison */}
          <div>
            <h4 className="font-semibold text-foreground mb-1">Scale Factors</h4>
            <div className="space-y-1.5">
              {[1, 10, 100].map(sf => {
                const meta = SF_META[sf];
                return (
                  <div key={sf} className="border border-border rounded px-2 py-1.5 text-[11px]">
                    <div className="font-medium text-foreground">{meta.label}</div>
                    <div className="flex items-center gap-3 text-muted-foreground mt-0.5">
                      <span className="flex items-center gap-0.5"><HardDrive size={10} />{meta.size}</span>
                      <span className="flex items-center gap-0.5"><Clock size={10} />{meta.time}</span>
                      <span className="flex items-center gap-0.5"><DollarSign size={10} />{meta.cost}</span>
                    </div>
                    <div className="text-muted-foreground/60 mt-0.5">Method: {meta.method}</div>
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-muted-foreground/60 mt-1 italic">
              Estimates are approximate and depend on cluster size and warehouse configuration.
            </p>
          </div>
        </div>

        <div className="p-3 border-t border-panel-border">
          <button
            onClick={() => setStep("config")}
            disabled={!canProceedToConfig}
            className={`w-full px-3 py-1.5 rounded-md text-[11px] font-medium flex items-center justify-center gap-1 ${
              canProceedToConfig
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
          >
            Next <ArrowRight size={12} />
          </button>
          {!canProceedToConfig && preflight && (
            <p className="text-[10px] text-status-warning mt-1 text-center">
              Resolve prerequisites above before proceeding.
            </p>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Step 2 — Configuration
  // ---------------------------------------------------------------------------

  if (step === "config") {
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
          <button onClick={() => setStep("info")}><ArrowLeft size={14} /></button>
          <span className="font-semibold text-foreground">TPC-DS Configuration</span>
          <span className="text-[10px] text-muted-foreground ml-auto">Step 2 of 2</span>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {/* Scale factor */}
          <div>
            <label className="font-semibold text-foreground block mb-1">Scale Factor</label>
            <div className="space-y-1">
              {[1, 10, 100].map(sf => (
                <label
                  key={sf}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded border cursor-pointer transition-colors ${
                    scaleFactor === sf
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-muted-foreground"
                  }`}
                >
                  <input
                    type="radio"
                    name="sf"
                    checked={scaleFactor === sf}
                    onChange={() => setScaleFactor(sf)}
                    className="accent-primary"
                  />
                  <span className="font-medium">{SF_META[sf].label}</span>
                  <span className="text-[10px] ml-auto">{SF_META[sf].size} &middot; {SF_META[sf].time}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Catalog name */}
          <div>
            <label className="font-semibold text-foreground block mb-1">Catalog Name</label>
            <input
              type="text"
              value={catalogName}
              onChange={e => setCatalogName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
              className="w-full px-2 py-1 border border-border rounded text-[12px] bg-background text-foreground"
              placeholder="delta_router_tpcds"
            />
            {catalogNameExists && (
              <p className="text-[10px] text-status-error mt-0.5">A catalog with this name already exists.</p>
            )}
            {!catalogNameValid && catalogName.length > 0 && (
              <p className="text-[10px] text-status-warning mt-0.5">Must start with a letter, use only lowercase letters, numbers, and underscores.</p>
            )}
          </div>

          {/* Schema name (auto-derived) */}
          <div>
            <label className="font-semibold text-foreground block mb-1">Schema Name</label>
            <div className="px-2 py-1 border border-border rounded text-[12px] bg-muted text-muted-foreground">
              {schemaName}
            </div>
            <p className="text-[10px] text-muted-foreground mt-0.5">Auto-derived from scale factor.</p>
          </div>

          {createError && (
            <div className="text-[11px] text-status-error bg-status-error/10 px-2 py-1.5 rounded flex items-center gap-1">
              <XCircle size={12} />
              {createError}
            </div>
          )}

          {/* Summary */}
          <div className="border border-border rounded px-2 py-1.5 text-[11px] space-y-0.5">
            <div className="font-semibold text-foreground mb-1">Summary</div>
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{catalogName}</span></p>
            <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{catalogName}.{schemaName}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{SF_META[scaleFactor].label} ({SF_META[scaleFactor].size})</span></p>
            <p className="text-muted-foreground">Tables: <span className="text-foreground">25 TPC-DS tables</span></p>
            <p className="text-muted-foreground">Method: <span className="text-foreground">{SF_META[scaleFactor].method}</span></p>
            <p className="text-muted-foreground">Est. time: <span className="text-foreground">{SF_META[scaleFactor].time}</span></p>
          </div>
        </div>

        <div className="p-3 border-t border-panel-border">
          <button
            onClick={handleCreate}
            disabled={!canCreate}
            className={`w-full px-3 py-1.5 rounded-md text-[11px] font-medium ${
              canCreate
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
          >
            Create TPC-DS Data
          </button>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Step 3 — Running / Progress
  // ---------------------------------------------------------------------------

  if (step === "running") {
    const progress = status
      ? Math.round((status.tables_created / status.total_tables) * 100)
      : 0;

    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
          <Loader2 size={14} className="animate-spin text-primary" />
          <span className="font-semibold text-foreground">Creating TPC-DS Data</span>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground">
                {status?.job_run_id
                  ? `Databricks Job: ${status.job_state || "PENDING"}`
                  : `Creating tables: ${status?.tables_created ?? 0}/${status?.total_tables ?? 25}`
                }
              </span>
              <span className="text-foreground font-medium">{progress}%</span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-300"
                style={{ width: `${Math.max(progress, 2)}%` }}
              />
            </div>

            {status?.elapsed_time_seconds != null && (
              <div className="text-[10px] text-muted-foreground">
                Elapsed: {formatElapsed(status.elapsed_time_seconds)}
              </div>
            )}
          </div>

          <div className="border border-border rounded px-2 py-1.5 text-[11px] space-y-0.5">
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{status?.catalog_name ?? catalogName}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{SF_META[scaleFactor]?.label}</span></p>
            {createResponse?.method && (
              <p className="text-muted-foreground">Method: <span className="text-foreground">{createResponse.method === "ctas" ? "CTAS from samples" : "Databricks Job"}</span></p>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Step 4 — Done (success or failure)
  // ---------------------------------------------------------------------------

  if (step === "done") {
    const success = status?.status === "ready";
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-2">
          {success
            ? <CheckCircle2 size={14} className="text-status-success" />
            : <XCircle size={14} className="text-status-error" />
          }
          <span className="font-semibold text-foreground">
            {success ? "TPC-DS Data Created" : "Creation Failed"}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {success ? (
            <>
              <div className="text-[11px] text-status-success bg-status-success/10 px-2 py-1.5 rounded flex items-center gap-1.5">
                <Check size={12} />
                <span>TPC-DS {SF_META[scaleFactor]?.label} created successfully!</span>
              </div>
              <div className="border border-border rounded px-2 py-1.5 text-[11px] space-y-0.5">
                <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{status?.catalog_name}</span></p>
                <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{status?.catalog_name}.{status?.schema_name}</span></p>
                <p className="text-muted-foreground">Tables: <span className="text-foreground">{status?.tables_created}/{status?.total_tables}</span></p>
              </div>
              <p className="text-[10px] text-muted-foreground">
                Browse the new catalog in the Catalog tab to see all TPC-DS tables.
                EXTERNAL USE SCHEMA has been granted — DuckDB can read these tables immediately.
              </p>
            </>
          ) : (
            <>
              <div className="text-[11px] text-status-error bg-status-error/10 px-2 py-1.5 rounded flex items-start gap-1.5">
                <XCircle size={12} className="shrink-0 mt-0.5" />
                <span>{status?.error_message || "An unknown error occurred."}</span>
              </div>
            </>
          )}
        </div>

        <div className="p-3 border-t border-panel-border space-y-1.5">
          <button
            onClick={handleReset}
            className="w-full px-3 py-1.5 bg-primary text-primary-foreground rounded-md text-[11px] font-medium"
          >
            {success ? "Done" : "Back to TPC-DS"}
          </button>
          {!success && (
            <button
              onClick={() => { setCreateError(null); setStep("config"); }}
              className="w-full px-3 py-1.5 border border-border text-foreground rounded-md text-[11px] font-medium"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  return null;
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const PrereqRow: React.FC<{ ok: boolean; label: string }> = ({ ok, label }) => (
  <div className="flex items-center gap-1.5">
    {ok
      ? <CheckCircle2 size={12} className="text-status-success shrink-0" />
      : <XCircle size={12} className="text-status-error shrink-0" />
    }
    <span className={ok ? "text-foreground" : "text-status-error"}>{label}</span>
  </div>
);

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
