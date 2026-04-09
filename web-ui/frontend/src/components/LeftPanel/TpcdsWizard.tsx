import React, { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import type {
  TpcdsPreFlight,
  TpcdsCreateResponse,
  TpcdsStatusResponse,
} from "@/types";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  X,
  Database,
  CheckCircle2,
  XCircle,
  Loader2,
  HardDrive,
  Clock,
  DollarSign,
  Info,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Constants — hardcoded catalog path
// ---------------------------------------------------------------------------

const TPCDS_CATALOG = "delta_router_tpcds";

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
  sf: number;
  label: string;
  schema: string;
  size: string;
  time: string;
  cost: string;
  method: string;
}

const SCALE_FACTORS: SfMeta[] = [
  { sf: 1, label: "SF1", schema: "sf1", size: "~1 GB", time: "~2-5 min", cost: "Minimal (existing warehouse)", method: "CTAS from samples" },
  { sf: 10, label: "SF10", schema: "sf10", size: "~10 GB", time: "~10-15 min", cost: "~$2-5 (Databricks Job)", method: "DuckDB dsdgen Job" },
  { sf: 100, label: "SF100", schema: "sf100", size: "~100 GB", time: "~30-60 min", cost: "~$10-20 (Databricks Job)", method: "DuckDB dsdgen Job" },
];

// ---------------------------------------------------------------------------
// Per-SF existence state
// ---------------------------------------------------------------------------

interface SfStatus {
  sf: number;
  exists: boolean;
  loading: boolean;
}

// ---------------------------------------------------------------------------
// Mock API helpers
// ---------------------------------------------------------------------------

// In mock mode, SF1 is pre-existing; SF10/SF100 are not
const mockExistingSfs = new Set<number>([1]);

function mockPreflight(): TpcdsPreFlight {
  return { samples_available: true, metastore_external_access: true, warehouse_configured: true };
}

function mockCheckSf(sf: number): boolean {
  return mockExistingSfs.has(sf);
}

function mockCreate(sf: number): TpcdsCreateResponse {
  // Simulate creation — after 2s mark as existing
  setTimeout(() => { mockExistingSfs.add(sf); }, 2000);
  return {
    id: Date.now(),
    catalog_name: TPCDS_CATALOG,
    schema_name: `sf${sf}`,
    scale_factor: sf,
    status: "creating",
    method: sf === 1 ? "ctas" : "job",
  };
}

function mockStatus(sf: number): TpcdsStatusResponse {
  const exists = mockExistingSfs.has(sf);
  return {
    id: 0,
    catalog_name: TPCDS_CATALOG,
    schema_name: `sf${sf}`,
    scale_factor: sf,
    status: exists ? "ready" : "creating",
    tables_created: exists ? 25 : 12,
    total_tables: 25,
    error_message: null,
    job_run_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const TpcdsSetupDialog: React.FC<TpcdsSetupDialogProps> = ({ open, onClose, onComplete }) => {
  const mock = isMockMode();

  // Wizard step
  const [step, setStep] = useState<"detect" | "info" | "create" | "running" | "done">("detect");

  // Per-SF existence detection
  const [sfStatuses, setSfStatuses] = useState<SfStatus[]>(
    SCALE_FACTORS.map(sf => ({ sf: sf.sf, exists: false, loading: true }))
  );
  const [detectError, setDetectError] = useState<string | null>(null);

  // Preflight
  const [preflight, setPreflight] = useState<TpcdsPreFlight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  // Selected SF to create
  const [selectedSf, setSelectedSf] = useState<number | null>(null);

  // Running state
  const [createResponse, setCreateResponse] = useState<TpcdsCreateResponse | null>(null);
  const [status, setStatus] = useState<TpcdsStatusResponse | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Detection — check which SFs already exist
  // ---------------------------------------------------------------------------

  const detectSfs = useCallback(async () => {
    setDetectError(null);
    setSfStatuses(SCALE_FACTORS.map(sf => ({ sf: sf.sf, exists: false, loading: true })));

    try {
      if (mock) {
        // Simulate a brief delay then check
        await new Promise(r => setTimeout(r, 300));
        setSfStatuses(SCALE_FACTORS.map(sf => ({
          sf: sf.sf,
          exists: mockCheckSf(sf.sf),
          loading: false,
        })));
      } else {
        // Real API: check each SF by trying to list tables in the schema
        // Backend endpoint: GET /api/tpcds/detect returns { sf1: bool, sf10: bool, sf100: bool }
        const result = await api.get<Record<string, boolean>>("/api/tpcds/detect");
        setSfStatuses(SCALE_FACTORS.map(sf => ({
          sf: sf.sf,
          exists: result[sf.schema] ?? false,
          loading: false,
        })));
      }
    } catch (err) {
      setDetectError(err instanceof Error ? err.message : "Detection failed");
      setSfStatuses(SCALE_FACTORS.map(sf => ({ sf: sf.sf, exists: false, loading: false })));
    }
  }, [mock]);

  useEffect(() => {
    if (open) {
      setStep("detect");
      detectSfs();
    }
  }, [open, detectSfs]);

  // ---------------------------------------------------------------------------
  // Preflight
  // ---------------------------------------------------------------------------

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

  const startPolling = (id: number, sf: number) => {
    const interval = setInterval(async () => {
      try {
        let s: TpcdsStatusResponse;
        if (mock) {
          s = mockStatus(sf);
        } else {
          s = await api.get<TpcdsStatusResponse>(`/api/tpcds/status/${id}`);
        }
        setStatus(s);
        if (s.status === "ready" || s.status === "failed") {
          clearInterval(interval);
          pollRef.current = null;
          if (s.status === "ready") {
            // Update local SF status
            setSfStatuses(prev => prev.map(x => x.sf === sf ? { ...x, exists: true } : x));
            onComplete?.();
          }
          setStep("done");
        }
      } catch {
        // keep polling
      }
    }, mock ? 500 : 3000);
    pollRef.current = interval;
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const allDetecting = sfStatuses.every(s => s.loading);
  const missingSfs = sfStatuses.filter(s => !s.exists && !s.loading);
  const existingSfs = sfStatuses.filter(s => s.exists && !s.loading);
  const allConfigured = !allDetecting && missingSfs.length === 0;

  const canProceedToCreate = preflight != null
    && preflight.metastore_external_access
    && preflight.warehouse_configured
    && selectedSf != null;

  const selectedMeta = SCALE_FACTORS.find(sf => sf.sf === selectedSf);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleSetupClick = async () => {
    await loadPreflight();
    // Pre-select the first missing SF
    if (missingSfs.length > 0 && selectedSf === null) {
      setSelectedSf(missingSfs[0].sf);
    }
    setStep("info");
  };

  const handleCreate = async () => {
    if (selectedSf === null) return;
    setCreateError(null);
    setStep("running");
    try {
      let resp: TpcdsCreateResponse;
      if (mock) {
        resp = mockCreate(selectedSf);
      } else {
        resp = await api.post<TpcdsCreateResponse>("/api/tpcds/create", {
          catalog_name: TPCDS_CATALOG,
          schema_name: `sf${selectedSf}`,
          scale_factor: selectedSf,
        });
      }
      setCreateResponse(resp);
      setStatus({
        id: resp.id,
        catalog_name: TPCDS_CATALOG,
        schema_name: `sf${selectedSf}`,
        scale_factor: selectedSf,
        status: "creating",
        tables_created: 0,
        total_tables: 25,
        error_message: null,
        job_run_id: resp.job_run_id ?? null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      startPolling(resp.id, selectedSf);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Creation failed");
      setStep("create");
    }
  };

  const handleClose = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    setStep("detect");
    setCreateResponse(null);
    setStatus(null);
    setCreateError(null);
    setSelectedSf(null);
    setPreflight(null);
    onClose();
  };

  const handleCreateAnother = () => {
    setCreateResponse(null);
    setStatus(null);
    setCreateError(null);
    setSelectedSf(null);
    // Re-detect to refresh statuses
    setStep("detect");
    detectSfs();
  };

  // ---------------------------------------------------------------------------
  // Don't render when closed
  // ---------------------------------------------------------------------------

  if (!open) return null;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">
      {step === "detect" && renderDetect()}
      {step === "info" && renderInfo()}
      {step === "create" && renderCreate()}
      {step === "running" && renderRunning()}
      {step === "done" && renderDone()}
    </div>
  );

  // ---------------------------------------------------------------------------
  // Step: Detect — show per-SF status
  // ---------------------------------------------------------------------------

  function renderDetect() {
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <Database size={15} className="text-primary" />
          <span className="font-semibold text-foreground text-[13px] flex-1">TPC-DS Data Setup</span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground"><X size={15} /></button>
        </div>

        <div className="px-4 py-3 text-[12px] text-muted-foreground border-b border-border">
          TPC-DS benchmark tables are stored in <span className="font-mono text-foreground">{TPCDS_CATALOG}</span> as managed Delta tables.
          Three scale factors are available — each is independent.
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {allDetecting ? (
            <div className="flex items-center gap-2 py-4 justify-center text-[12px] text-muted-foreground">
              <LoadingSpinner size={14} />
              <span>Checking existing datasets…</span>
            </div>
          ) : detectError ? (
            <div className="text-[12px] text-status-error bg-status-error/10 px-3 py-2 rounded-md flex items-center gap-1.5">
              <XCircle size={13} />
              {detectError}
            </div>
          ) : (
            <>
              {SCALE_FACTORS.map(meta => {
                const sfSt = sfStatuses.find(s => s.sf === meta.sf);
                const exists = sfSt?.exists ?? false;
                return (
                  <div
                    key={meta.sf}
                    className={`border rounded-md px-3 py-2.5 text-[12px] ${
                      exists ? "border-status-success/30 bg-status-success/5" : "border-border"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {exists ? (
                        <CheckCircle2 size={14} className="text-status-success shrink-0" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full border-2 border-muted-foreground/40 shrink-0" />
                      )}
                      <span className="font-semibold text-foreground">{meta.label}</span>
                      <span className="text-[11px] text-muted-foreground ml-auto">{meta.size}</span>
                    </div>
                    <div className="ml-[22px] mt-1 text-[11px] text-muted-foreground">
                      {exists ? (
                        <span className="text-status-success">
                          Dataset found in <span className="font-mono">{TPCDS_CATALOG}.{meta.schema}</span>
                        </span>
                      ) : (
                        <span>Not created · {meta.time} · {meta.cost}</span>
                      )}
                    </div>
                  </div>
                );
              })}

              {allConfigured && (
                <div className="text-[12px] text-status-success bg-status-success/10 px-3 py-2.5 rounded-md flex items-center gap-2 mt-2">
                  <Check size={14} />
                  <span>All TPC-DS datasets are configured. You're ready to run benchmarks.</span>
                </div>
              )}
            </>
          )}
        </div>

        {!allDetecting && !allConfigured && (
          <div className="px-4 py-3 border-t border-panel-border">
            <button
              onClick={handleSetupClick}
              className="w-full px-3 py-2 bg-primary text-primary-foreground rounded-md text-[12px] font-medium hover:bg-primary/90 transition-colors"
            >
              {existingSfs.length > 0 ? "Create Missing Datasets" : "Set Up TPC-DS Data"}
            </button>
          </div>
        )}

        {allConfigured && (
          <div className="px-4 py-3 border-t border-panel-border">
            <button
              onClick={handleClose}
              className="w-full px-3 py-2 bg-primary text-primary-foreground rounded-md text-[12px] font-medium hover:bg-primary/90 transition-colors"
            >
              Done
            </button>
          </div>
        )}
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Info / Preflight + SF selection
  // ---------------------------------------------------------------------------

  function renderInfo() {
    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <button onClick={() => setStep("detect")} className="text-muted-foreground hover:text-foreground"><ArrowLeft size={15} /></button>
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
              25 standard TPC-DS tables as managed Delta tables in <span className="font-mono text-foreground">{TPCDS_CATALOG}</span>.
              Access is granted to all workspace users automatically (EXTERNAL USE SCHEMA for DuckDB).
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

          {/* Scale factor selection — only missing ones are selectable */}
          <div>
            <h4 className="font-semibold text-foreground text-[12px] mb-1.5">Select Scale Factor</h4>
            <div className="space-y-1.5">
              {SCALE_FACTORS.map(meta => {
                const sfSt = sfStatuses.find(s => s.sf === meta.sf);
                const exists = sfSt?.exists ?? false;
                if (exists) {
                  return (
                    <div key={meta.sf} className="flex items-center gap-2 px-3 py-2 rounded-md border border-status-success/30 bg-status-success/5 text-[12px]">
                      <CheckCircle2 size={14} className="text-status-success shrink-0" />
                      <span className="font-medium text-muted-foreground">{meta.label}</span>
                      <span className="text-[11px] text-status-success ml-auto">Already exists</span>
                    </div>
                  );
                }
                return (
                  <label
                    key={meta.sf}
                    className={`flex items-center gap-2 px-3 py-2 rounded-md border cursor-pointer transition-colors text-[12px] ${
                      selectedSf === meta.sf
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border text-muted-foreground hover:border-muted-foreground"
                    }`}
                  >
                    <input
                      type="radio"
                      name="sf"
                      checked={selectedSf === meta.sf}
                      onChange={() => setSelectedSf(meta.sf)}
                      className="accent-primary"
                    />
                    <span className="font-medium">{meta.label}</span>
                    <span className="text-[11px] ml-auto">{meta.size} · {meta.time}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-panel-border">
          <button
            onClick={() => setStep("create")}
            disabled={!canProceedToCreate}
            className={`w-full px-3 py-2 rounded-md text-[12px] font-medium flex items-center justify-center gap-1.5 transition-colors ${
              canProceedToCreate
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            }`}
          >
            Next <ArrowRight size={13} />
          </button>
          {!canProceedToCreate && preflight && !selectedSf && (
            <p className="text-[11px] text-muted-foreground mt-1.5 text-center">
              Select a scale factor to continue.
            </p>
          )}
          {!canProceedToCreate && preflight && selectedSf && !preflight.metastore_external_access && (
            <p className="text-[11px] text-status-warning mt-1.5 text-center">
              Resolve prerequisites above before proceeding.
            </p>
          )}
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Step: Create confirmation (replaces old "config" step)
  // ---------------------------------------------------------------------------

  function renderCreate() {
    if (!selectedMeta) return null;

    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <button onClick={() => setStep("info")} className="text-muted-foreground hover:text-foreground"><ArrowLeft size={15} /></button>
          <span className="font-semibold text-foreground text-[13px] flex-1">Confirm Creation</span>
          <span className="text-[11px] text-muted-foreground">Step 2 of 2</span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground ml-2"><X size={15} /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {createError && (
            <div className="text-[12px] text-status-error bg-status-error/10 px-3 py-2 rounded-md flex items-center gap-1.5">
              <XCircle size={13} />
              {createError}
            </div>
          )}

          {/* Summary */}
          <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1.5">
            <div className="font-semibold text-foreground mb-2">Summary</div>
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{TPCDS_CATALOG}</span></p>
            <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{TPCDS_CATALOG}.{selectedMeta.schema}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{selectedMeta.label} ({selectedMeta.size})</span></p>
            <p className="text-muted-foreground">Tables: <span className="text-foreground">25 TPC-DS tables</span></p>
            <p className="text-muted-foreground">Method: <span className="text-foreground">{selectedMeta.method}</span></p>
            <p className="text-muted-foreground">Est. time: <span className="text-foreground">{selectedMeta.time}</span></p>
            <p className="text-muted-foreground">Est. cost: <span className="text-foreground">{selectedMeta.cost}</span></p>
          </div>

          <div className="text-[12px] text-muted-foreground leading-relaxed bg-muted/50 px-3 py-2.5 rounded-md">
            <p>After creation, access will be granted to all users across all workspaces sharing your metastore.</p>
          </div>
        </div>

        <div className="px-4 py-3 border-t border-panel-border">
          <button
            onClick={handleCreate}
            className="w-full px-3 py-2 bg-primary text-primary-foreground rounded-md text-[12px] font-medium hover:bg-primary/90 transition-colors"
          >
            Create {selectedMeta.label} Data
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
    const meta = SCALE_FACTORS.find(sf => sf.sf === selectedSf);

    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          <Loader2 size={15} className="animate-spin text-primary" />
          <span className="font-semibold text-foreground text-[13px] flex-1">Creating {meta?.label ?? "TPC-DS"} Data</span>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[12px]">
              <span className="text-muted-foreground">
                {status?.job_run_id
                  ? `Databricks Job: ${(status as any).job_state || "PENDING"}`
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
          </div>

          <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1">
            <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{TPCDS_CATALOG}</span></p>
            <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{TPCDS_CATALOG}.{meta?.schema}</span></p>
            <p className="text-muted-foreground">Scale: <span className="text-foreground">{meta?.label}</span></p>
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
    const meta = SCALE_FACTORS.find(sf => sf.sf === selectedSf);
    const hasMoreToCreate = sfStatuses.some(s => !s.exists && s.sf !== selectedSf);

    return (
      <>
        <div className="px-4 py-3 border-b border-panel-border flex items-center gap-2">
          {success
            ? <CheckCircle2 size={15} className="text-status-success" />
            : <XCircle size={15} className="text-status-error" />
          }
          <span className="font-semibold text-foreground text-[13px] flex-1">
            {success ? `${meta?.label ?? "TPC-DS"} Data Created` : "Creation Failed"}
          </span>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground"><X size={15} /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {success ? (
            <>
              <div className="text-[12px] text-status-success bg-status-success/10 px-3 py-2.5 rounded-md flex items-center gap-2">
                <Check size={14} />
                <span>{meta?.label} created successfully!</span>
              </div>
              <div className="border border-border rounded-md px-3 py-2.5 text-[12px] space-y-1">
                <p className="text-muted-foreground">Catalog: <span className="text-foreground font-mono">{status?.catalog_name}</span></p>
                <p className="text-muted-foreground">Schema: <span className="text-foreground font-mono">{status?.catalog_name}.{status?.schema_name}</span></p>
                <p className="text-muted-foreground">Tables: <span className="text-foreground">{status?.tables_created}/{status?.total_tables}</span></p>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                Access has been granted to all workspace users. DuckDB can read these tables immediately via credential vending.
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
            Done
          </button>
          {success && hasMoreToCreate && (
            <button
              onClick={handleCreateAnother}
              className="w-full px-3 py-2 border border-border text-foreground rounded-md text-[12px] font-medium hover:bg-muted transition-colors"
            >
              Create Another Scale Factor
            </button>
          )}
          {!success && (
            <button
              onClick={() => { setCreateError(null); setStep("create"); }}
              className="w-full px-3 py-2 border border-border text-foreground rounded-md text-[12px] font-medium hover:bg-muted transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </>
    );
  }
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
