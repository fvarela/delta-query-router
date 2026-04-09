import React, { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";
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
// Props
// ---------------------------------------------------------------------------

interface TpcdsSetupDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called when TPC-DS data is successfully created — parent should update tpcdsConfigured */
  onComplete?: () => void;
}

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
// Mock API helpers — simulate backend responses in mock mode
// ---------------------------------------------------------------------------

let mockCatalogs: TpcdsCatalog[] = [];
let mockNextId = 1;

function mockPreflight(): TpcdsPreFlight {
  return { samples_available: true, metastore_external_access: true, warehouse_configured: true };
}

function mockCreate(catalogName: string, schemaName: string, scaleFactor: number): TpcdsCreateResponse {
  const id = mockNextId++;
  const cat: TpcdsCatalog = {
    id, catalog_name: catalogName, schema_name: schemaName, scale_factor: scaleFactor,
    status: "creating", tables_created: 0, total_tables: 25,
    error_message: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  };
  mockCatalogs.push(cat);
  // Simulate progress — after 2s mark as ready
  setTimeout(() => {
    const c = mockCatalogs.find(x => x.id === id);
    if (c) { c.status = "ready"; c.tables_created = 25; }
  }, 2000);
  return { id, catalog_name: catalogName, schema_name: schemaName, scale_factor: scaleFactor, status: "creating", method: scaleFactor === 1 ? "ctas" : "job" };
}

function mockStatus(id: number): TpcdsStatusResponse {
  const cat = mockCatalogs.find(x => x.id === id);
  if (!cat) return { id, catalog_name: "", schema_name: "", scale_factor: 1, status: "failed", tables_created: 0, total_tables: 25, error_message: "Not found", created_at: null, updated_at: null, job_run_id: null };
  return { ...cat, job_run_id: null };
}

function mockDeleteCatalog(catalogName: string) {
  mockCatalogs = mockCatalogs.filter(c => c.catalog_name !== catalogName);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const TpcdsSetupDialog: React.FC<TpcdsSetupDialogProps> = ({ open, onClose, onComplete }) => {
  const mock = isMockMode();

  // Wizard step
  const [step, setStep] = useState<"list" | "info" | "config" | "running" | "done">("list");

  // Preflight
  const [preflight, setPreflight] = useState<TpcdsPreFlight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  // Config
  const [catalogName, setCatalogName] = useState("delta_router_tpcds");
  const [scaleFactor, setScaleFactor] = useState<number>(1);
  const schemaName = `sf${scaleFactor}`;

  // Existing catalogs
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
      if (mock) {
        setCatalogs([...mockCatalogs]);
      } else {
        const list = await api.get<TpcdsCatalog[]>("/api/tpcds/catalogs");
        setCatalogs(list);
      }
    } catch {
      setCatalogs([]);
    }
    setCatalogsLoading(false);
  }, [mock]);

  useEffect(() => {
    if (open) loadCatalogs();
  }, [open, loadCatalogs]);

  const loadPreflight = async () => {
    setPreflightLoading(true);
    setPreflightError(null);
    try {
      if (mock) {
        setPreflight(mockPreflight());
      } else {
        const pf = await api.get<TpcdsPreFlight>("/api/tpcds/preflight");
        setPreflight(pf);
      }
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
        let s: TpcdsStatusResponse;
        if (mock) {
          s = mockStatus(id);
        } else {
          s = await api.get<TpcdsStatusResponse>(`/api/tpcds/status/${id}`);
        }
        setStatus(s);
        if (s.status === "ready" || s.status === "failed") {
          clearInterval(interval);
          pollRef.current = null;
          setStep("done");
          if (s.status === "ready") onComplete?.();
        }
      } catch {
        // keep polling
      }
    }, mock ? 500 : 3000);
    pollRef.current = interval;
  };

  // Cleanup polling on unmount or close
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
      let resp: TpcdsCreateResponse;
      if (mock) {
        resp = mockCreate(catalogName, schemaName, scaleFactor);
      } else {
        resp = await api.post<TpcdsCreateResponse>("/api/tpcds/create", {
          catalog_name: catalogName,
          schema_name: schemaName,
          scale_factor: scaleFactor,
        });
      }
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
      if (mock) {
        mockDeleteCatalog(deleteCatalog);
      } else {
        await api.del(`/api/tpcds/catalogs/${deleteCatalog}`);
      }
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

  const handleClose = () => {
    handleReset();
    onClose();
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
  // Don't render when closed
  // ---------------------------------------------------------------------------

  if (!open) return null;

  // ---------------------------------------------------------------------------
  // Render wrapper — modal dialog
  // ---------------------------------------------------------------------------

  const renderContent = () => {
    // Step: List (default)
    if (step === "list") return renderList();
    if (step === "info") return renderInfo();
    if (step === "config") return renderConfig();
    if (step === "running") return renderRunning();
    if (step === "done") return renderDone();
    return null;
  };

  // ---------------------------------------------------------------------------
  // Step: List — show existing catalogs + "Set Up" button
  // ---------------------------------------------------------------------------

  function renderList() {
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <Database size={15} className="text-primary" />
          <span className="font-semibold text-foreground text-[13px] flex-1">TPC-DS Data Setup</span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground"><X size={15} /></button>
        </div>

        <div className="px-4 py-3 text-[12px] text-muted-foreground border-b border-border">
          Create standardized TPC-DS benchmark tables in your workspace as managed Delta tables in a dedicated Unity Catalog catalog.
        </div>

        <div className="px-4 py-3">
          <button
            onClick={handleStartWizard}
            className="w-full px-3 py-2 bg-primary text-primary-foreground rounded-md text-[12px] font-medium hover:bg-primary/90 transition-colors"
          >
            Set Up TPC-DS Data
          </button>
        </div>

        {/* Existing catalogs */}
        {catalogsLoading ? (
          <div className="px-4 py-3"><LoadingSpinner size={14} /></div>
        ) : catalogs.length > 0 && (
          <div className="flex-1 overflow-y-auto border-t border-border">
            <div className="px-4 py-2 text-[11px] text-muted-foreground font-semibold uppercase tracking-wider">Created Datasets</div>
            {catalogs.map(cat => (
              <div key={cat.id} className="px-4 py-2 border-b border-border flex items-center gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-foreground text-[12px] truncate">{cat.catalog_name}</span>
                    <StatusBadge variant={
                      cat.status === "ready" ? "success"
                        : cat.status === "failed" ? "error"
                          : cat.status === "creating" ? "warning"
                            : "inactive"
                    }>
                      {cat.status}
                    </StatusBadge>
                  </div>
                  <div className="text-[11px] text-muted-foreground flex items-center gap-2 mt-0.5">
                    <span>SF{cat.scale_factor}</span>
                    <span>{cat.tables_created}/{cat.total_tables} tables</span>
                    {cat.created_at && <span>{new Date(cat.created_at).toLocaleDateString()}</span>}
                  </div>
                  {cat.error_message && (
                    <div className="text-[11px] text-status-error mt-0.5 truncate" title={cat.error_message}>
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
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Info / Preflight
  // ---------------------------------------------------------------------------

  function renderInfo() {
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <button onClick={handleReset} className="text-muted-foreground hover:text-foreground"><ArrowLeft size={15} /></button>
          <span className="font-semibold text-foreground text-[13px] flex-1">TPC-DS Setup</span>
          <span className="text-[11px] text-muted-foreground">Step 1 of 2</span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground ml-2"><X size={15} /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* What gets created */}
          <div>
            <h4 className="font-semibold text-foreground text-[12px] mb-1.5 flex items-center gap-1.5">
              <Info size={13} className="text-primary" />
              What gets created
            </h4>
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              A new Unity Catalog catalog with one schema containing all 25 standard TPC-DS tables as managed Delta tables.
              EXTERNAL USE SCHEMA is granted automatically so DuckDB can read the data.
            </p>
          </div>

          {/* Prerequisites */}
          <div>
            <h4 className="font-semibold text-foreground text-[12px] mb-1.5">Prerequisites</h4>
            {preflightLoading ? (
              <LoadingSpinner size={14} />
            ) : preflightError ? (
              <div className="text-[12px] text-status-error">{preflightError}</div>
            ) : preflight ? (
              <div className="space-y-1.5 text-[12px]">
                <PrereqRow ok={preflight.metastore_external_access} label="Metastore external access enabled" />
                <PrereqRow ok={preflight.warehouse_configured} label="SQL Warehouse configured" />
                <PrereqRow ok={true} label="Workspace connected" />
              </div>
            ) : null}
          </div>

          {/* Scale factor comparison */}
          <div>
            <h4 className="font-semibold text-foreground text-[12px] mb-1.5">Available Scale Factors</h4>
            <div className="space-y-2">
              {[1, 10, 100].map(sf => {
                const meta = SF_META[sf];
                return (
                  <div key={sf} className="border border-border rounded-md px-3 py-2 text-[12px]">
                    <div className="font-semibold text-foreground">{meta.label}</div>
                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground mt-1">
                      <span className="flex items-center gap-1"><HardDrive size={11} />{meta.size}</span>
                      <span className="flex items-center gap-1"><Clock size={11} />{meta.time}</span>
                      <span className="flex items-center gap-1"><DollarSign size={11} />{meta.cost}</span>
                    </div>
                    <div className="text-[11px] text-muted-foreground/70 mt-0.5">Method: {meta.method}</div>
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-muted-foreground/70 mt-2 italic">
              Estimates are approximate and depend on cluster size and warehouse configuration.
            </p>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-panel-border">
          <button
            onClick={() => setStep("config")}
            disabled={!canProceedToConfig}
            className={`w-full px-3 py-2 rounded-md text-[12px] font-medium flex items-center justify-center gap-1.5 transition-colors ${
              canProceedToConfig
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
          >
            Next <ArrowRight size={13} />
          </button>
          {!canProceedToConfig && preflight && (
            <p className="text-[11px] text-status-warning mt-1.5 text-center">
              Resolve prerequisites above before proceeding.
            </p>
          )}
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Configuration
  // ---------------------------------------------------------------------------

  function renderConfig() {
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <button onClick={() => setStep("info")} className="text-muted-foreground hover:text-foreground"><ArrowLeft size={15} /></button>
          <span className="font-semibold text-foreground text-[13px] flex-1">TPC-DS Configuration</span>
          <span className="text-[11px] text-muted-foreground">Step 2 of 2</span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground ml-2"><X size={15} /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Scale factor */}
          <div>
            <label className="font-semibold text-foreground text-[12px] block mb-1.5">Scale Factor</label>
            <div className="space-y-1.5">
              {[1, 10, 100].map(sf => (
                <label
                  key={sf}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md border cursor-pointer transition-colors text-[12px] ${
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
                  <span className="text-[11px] ml-auto">{SF_META[sf].size} · {SF_META[sf].time}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Catalog name */}
          <div>
            <label className="font-semibold text-foreground text-[12px] block mb-1.5">Catalog Name</label>
            <input
              type="text"
              value={catalogName}
              onChange={e => setCatalogName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
              className="w-full px-3 py-2 border border-border rounded-md text-[12px] bg-background text-foreground focus:border-primary focus:ring-1 focus:ring-primary/30 outline-none transition-colors"
              placeholder="delta_router_tpcds"
            />
            {catalogNameExists && (
              <p className="text-[11px] text-status-error mt-1">A catalog with this name already exists.</p>
            )}
            {!catalogNameValid && catalogName.length > 0 && (
              <p className="text-[11px] text-status-warning mt-1">Must start with a letter, use only lowercase letters, numbers, and underscores.</p>
            )}
          </div>

          {/* Schema name (auto-derived) */}
          <div>
            <label className="font-semibold text-foreground text-[12px] block mb-1.5">Schema Name</label>
            <div className="px-3 py-2 border border-border rounded-md text-[12px] bg-muted text-muted-foreground">
              {schemaName}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1">Auto-derived from scale factor.</p>
          </div>

          {createError && (
            <div className="text-[12px] text-status-error bg-status-error/10 px-3 py-2 rounded-md flex items-center gap-1.5">
              <XCircle size={13} />
              {createError}
            </div>
          )}

          {/* Summary */}
          <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1">
            <div className="font-semibold text-foreground mb-1.5">Summary</div>
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{catalogName}</span></p>
            <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{catalogName}.{schemaName}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{SF_META[scaleFactor].label} ({SF_META[scaleFactor].size})</span></p>
            <p className="text-muted-foreground">Tables: <span className="text-foreground">25 TPC-DS tables</span></p>
            <p className="text-muted-foreground">Method: <span className="text-foreground">{SF_META[scaleFactor].method}</span></p>
            <p className="text-muted-foreground">Est. time: <span className="text-foreground">{SF_META[scaleFactor].time}</span></p>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-panel-border">
          <button
            onClick={handleCreate}
            disabled={!canCreate}
            className={`w-full px-3 py-2 rounded-md text-[12px] font-medium transition-colors ${
              canCreate
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
          >
            Create TPC-DS Data
          </button>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Running / Progress
  // ---------------------------------------------------------------------------

  function renderRunning() {
    const progress = status
      ? Math.round((status.tables_created / status.total_tables) * 100)
      : 0;

    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <Loader2 size={15} className="animate-spin text-primary" />
          <span className="font-semibold text-foreground text-[13px] flex-1">Creating TPC-DS Data</span>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-muted-foreground">
                {status?.job_run_id
                  ? `Databricks Job: ${status.job_state || "PENDING"}`
                  : `Creating tables: ${status?.tables_created ?? 0}/${status?.total_tables ?? 25}`
                }
              </span>
              <span className="text-foreground font-semibold">{progress}%</span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-500"
                style={{ width: `${Math.max(progress, 3)}%` }}
              />
            </div>

            {status?.elapsed_time_seconds != null && (
              <div className="text-[11px] text-muted-foreground">
                Elapsed: {formatElapsed(status.elapsed_time_seconds)}
              </div>
            )}
          </div>

          <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1">
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{status?.catalog_name ?? catalogName}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{SF_META[scaleFactor]?.label}</span></p>
            {createResponse?.method && (
              <p className="text-muted-foreground">Method: <span className="text-foreground">{createResponse.method === "ctas" ? "CTAS from samples" : "Databricks Job"}</span></p>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground italic">
            This may take several minutes. You can close this dialog — creation will continue in the background.
          </p>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Done (success or failure)
  // ---------------------------------------------------------------------------

  function renderDone() {
    const success = status?.status === "ready";
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          {success
            ? <CheckCircle2 size={15} className="text-status-success" />
            : <XCircle size={15} className="text-status-error" />
          }
          <span className="font-semibold text-foreground text-[13px] flex-1">
            {success ? "TPC-DS Data Created" : "Creation Failed"}
          </span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground"><X size={15} /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {success ? (
            <>
              <div className="text-[12px] text-status-success bg-status-success/10 px-3 py-2.5 rounded-md flex items-center gap-2">
                <Check size={14} />
                <span>TPC-DS {SF_META[scaleFactor]?.label} created successfully!</span>
              </div>
              <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1">
                <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{status?.catalog_name}</span></p>
                <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{status?.catalog_name}.{status?.schema_name}</span></p>
                <p className="text-muted-foreground">Tables: <span className="text-foreground">{status?.tables_created}/{status?.total_tables}</span></p>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Browse the new catalog in the Catalog tab to see all TPC-DS tables.
                EXTERNAL USE SCHEMA has been granted — DuckDB can read these tables immediately.
              </p>
            </>
          ) : (
            <div className="text-[12px] text-status-error bg-status-error/10 px-3 py-2.5 rounded-md flex items-start gap-2">
              <XCircle size={14} className="shrink-0 mt-0.5" />
              <span>{status?.error_message || "An unknown error occurred."}</span>
            </div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-panel-border space-y-2">
          <button
            onClick={handleClose}
            className="w-full px-3 py-2 bg-primary text-primary-foreground rounded-md text-[12px] font-medium hover:bg-primary/90 transition-colors"
          >
            {success ? "Done" : "Close"}
          </button>
          {!success && (
            <button
              onClick={() => { setCreateError(null); setStep("config"); }}
              className="w-full px-3 py-2 border border-border text-foreground rounded-md text-[12px] font-medium hover:bg-muted transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Modal shell
  // ---------------------------------------------------------------------------

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={handleClose}>
      <div
        className="bg-background border border-panel-border rounded-lg shadow-panel-md w-[520px] max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {renderContent()}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const PrereqRow: React.FC<{ ok: boolean; label: string }> = ({ ok, label }) => (
  <div className="flex items-center gap-2">
    {ok
      ? <CheckCircle2 size={13} className="text-status-success shrink-0" />
      : <XCircle size={13} className="text-status-error shrink-0" />
    }
    <span className={`text-[12px] ${ok ? "text-foreground" : "text-status-error"}`}>{label}</span>
  </div>
);

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
