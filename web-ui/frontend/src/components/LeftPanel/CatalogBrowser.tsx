import React, { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import type { CatalogInfo, SchemaInfo, TableInfo, MetastoreAccessStatus } from "@/types";
import { FOREIGN_FORMATS } from "@/types";
import { ChevronRight, ChevronDown, Folder, Table2, Database, ShieldCheck, ShieldOff, AlertTriangle, Globe, Lock, Unlock } from "lucide-react";

/** Three-color classification for the catalog tree indicator bar.
 *  Green  = DuckDB-readable (Delta / Iceberg with external access flags)
 *  Amber  = Databricks-only (native format but blocked, or VIEWs)
 *  Red    = Foreign / federated tables (always Databricks)
 */
const tableBarColor = (t: TableInfo): string => {
  if (t.table_type === "FOREIGN") return "bg-red-500";
  if (t.external_engine_read_support) return "bg-status-success";
  return "bg-status-warning";
};

/** Tooltip text for the bar color */
const tableBarTitle = (t: TableInfo): string => {
  if (t.table_type === "FOREIGN") return "Foreign / federated — Databricks only";
  if (t.external_engine_read_support) return "DuckDB readable";
  return "Databricks only";
};

const formatBytes = (b: number | null) => {
  if (!b) return "-";
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(1)} GB`;
};

const formatNumber = (n: number | null) => n == null ? "-" : n.toLocaleString();

export const CatalogBrowser: React.FC = () => {
  const { connectedWorkspace, setEditorSql, setCollectionContext } = useApp();
  const [catalogs, setCatalogs] = useState<CatalogInfo[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [schemas, setSchemas] = useState<Record<string, SchemaInfo[]>>({});
  const [tables, setTables] = useState<Record<string, TableInfo[]>>({});
  const [loadingKeys, setLoadingKeys] = useState<Set<string>>(new Set());
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [treeErrors, setTreeErrors] = useState<Record<string, string>>({});

  // Metastore external access state (T87)
  const [metastoreAccess, setMetastoreAccess] = useState<MetastoreAccessStatus | null>(null);
  const [metastoreLoading, setMetastoreLoading] = useState(false);

  // EUS grant/revoke loading state (T88)
  const [eusLoading, setEusLoading] = useState<Set<string>>(new Set());

  // Fetch metastore external access on workspace connect
  useEffect(() => {
    if (!connectedWorkspace) {
      setMetastoreAccess(null);
      return;
    }
    setMetastoreLoading(true);
    api.get<MetastoreAccessStatus>("/api/metastore/external-access")
      .then(setMetastoreAccess)
      .catch(() => setMetastoreAccess(null))
      .finally(() => setMetastoreLoading(false));
  }, [connectedWorkspace]);

  // EUS grant/revoke handlers
  const handleGrantEus = async (catalog: string, schema: string) => {
    const key = `${catalog}.${schema}`;
    setEusLoading(prev => new Set(prev).add(key));
    try {
      await api.post(`/api/databricks/catalogs/${catalog}/schemas/${schema}/external-use`);
      // Update local schema state
      setSchemas(prev => ({
        ...prev,
        [catalog]: prev[catalog]?.map(s =>
          s.name === schema ? { ...s, external_use_schema: true } : s
        ) ?? [],
      }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to grant";
      setTreeErrors(prev => ({ ...prev, [key]: msg }));
    }
    setEusLoading(prev => { const n = new Set(prev); n.delete(key); return n; });
  };

  const handleRevokeEus = async (catalog: string, schema: string) => {
    const key = `${catalog}.${schema}`;
    setEusLoading(prev => new Set(prev).add(key));
    try {
      await api.del(`/api/databricks/catalogs/${catalog}/schemas/${schema}/external-use`);
      setSchemas(prev => ({
        ...prev,
        [catalog]: prev[catalog]?.map(s =>
          s.name === schema ? { ...s, external_use_schema: false } : s
        ) ?? [],
      }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to revoke";
      setTreeErrors(prev => ({ ...prev, [key]: msg }));
    }
    setEusLoading(prev => { const n = new Set(prev); n.delete(key); return n; });
  };

  useEffect(() => {
    if (!connectedWorkspace) {
      setCatalogs([]);
      setError(null);
      return;
    }
    setLoadingKeys(new Set(["catalogs"]));
    setError(null);
    api.get<CatalogInfo[]>("/api/databricks/catalogs")
      .then(c => {
        setCatalogs(c);
        setLoadingKeys(prev => { const n = new Set(prev); n.delete("catalogs"); return n; });
      })
      .catch(err => {
        setCatalogs([]);
        setLoadingKeys(prev => { const n = new Set(prev); n.delete("catalogs"); return n; });
        if (String(err).includes("400") || String(err).includes("No Databricks workspace")) {
          setError("Connect a Databricks workspace to browse catalogs.");
        } else {
          setError("Failed to load catalogs.");
        }
      });
  }, [connectedWorkspace]);

  const toggleCatalog = async (catalog: string) => {
    const key = catalog;
    if (expanded[key]) {
      setExpanded(prev => ({ ...prev, [key]: false }));
      return;
    }
    if (!schemas[catalog]) {
      setLoadingKeys(prev => new Set(prev).add(key));
      try {
        const s = await api.get<SchemaInfo[]>(`/api/databricks/catalogs/${catalog}/schemas`);
        setSchemas(prev => ({ ...prev, [catalog]: s }));
        setTreeErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load schemas";
        setTreeErrors(prev => ({ ...prev, [key]: msg }));
      }
      setLoadingKeys(prev => { const n = new Set(prev); n.delete(key); return n; });
    }
    setExpanded(prev => ({ ...prev, [key]: true }));
  };

  const toggleSchema = async (catalog: string, schema: string) => {
    const key = `${catalog}.${schema}`;
    if (expanded[key]) {
      setExpanded(prev => ({ ...prev, [key]: false }));
      return;
    }
    if (!tables[key]) {
      setLoadingKeys(prev => new Set(prev).add(key));
      try {
        const t = await api.get<TableInfo[]>(`/api/databricks/catalogs/${catalog}/schemas/${schema}/tables`);
        setTables(prev => ({ ...prev, [key]: t }));
        setTreeErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load tables";
        setTreeErrors(prev => ({ ...prev, [key]: msg }));
      }
      setLoadingKeys(prev => { const n = new Set(prev); n.delete(key); return n; });
    }
    setExpanded(prev => ({ ...prev, [key]: true }));
  };

  const handleTableClick = (table: TableInfo) => {
    setSelectedTable(selectedTable?.full_name === table.full_name ? null : table);
  };

  const handleLoadSample = (table: TableInfo) => {
    setEditorSql(`SELECT * FROM ${table.full_name} LIMIT 100`);
    setCollectionContext(null);
  };

  if (!connectedWorkspace) {
    return (
      <div className="flex flex-col h-full text-[12px]">
        <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5">
          <Database size={14} className="text-primary" />
          <span className="font-semibold text-foreground">Catalog Browser</span>
        </div>
        <div className="p-3 text-muted-foreground">
          Connect to a workspace to browse catalogs.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 text-[12px]">
        <Database size={14} className="text-primary" />
        <span className="font-semibold text-foreground flex-1">Catalog Browser</span>
        {/* Metastore external access indicator (T87) */}
        {metastoreLoading && <LoadingSpinner size={12} />}
        {metastoreAccess != null && (
          metastoreAccess.external_access_enabled
            ? <span className="flex items-center gap-0.5 text-status-success" title={`External access enabled on ${metastoreAccess.metastore_name}`}>
                <Globe size={12} />
              </span>
            : <span className="flex items-center gap-0.5 text-status-error" title={`External access disabled on ${metastoreAccess.metastore_name}`}>
                <AlertTriangle size={12} />
              </span>
        )}
      </div>
      {/* Warning banner when external access is disabled */}
      {metastoreAccess != null && !metastoreAccess.external_access_enabled && (
        <div className="px-3 py-2 bg-amber-500/10 border-b border-amber-500/30 text-[12px] text-amber-200 flex items-start gap-1.5">
          <AlertTriangle size={12} className="shrink-0 mt-0.5 text-amber-400" />
          <span>
            Metastore external access is disabled. DuckDB cannot read managed tables.
            A metastore admin must enable this in the Databricks workspace.
          </span>
        </div>
      )}
      <div className="flex-1 overflow-y-auto text-[12px]">
        {loadingKeys.has("catalogs") && <div className="p-3"><LoadingSpinner /></div>}
        {error && (
          <div className="p-3 flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-[12px] text-muted-foreground">{error}</p>
              {error === "Failed to load catalogs." && (
                <button
                  onClick={() => {
                    setError(null);
                    setLoadingKeys(new Set(["catalogs"]));
                    api.get<CatalogInfo[]>("/api/databricks/catalogs")
                      .then(c => {
                        setCatalogs(c);
                        setLoadingKeys(prev => { const n = new Set(prev); n.delete("catalogs"); return n; });
                      })
                      .catch(() => {
                        setLoadingKeys(prev => { const n = new Set(prev); n.delete("catalogs"); return n; });
                        setError("Failed to load catalogs.");
                      });
                  }}
                  className="mt-1.5 text-[11px] text-primary hover:text-primary/80 font-medium transition-colors"
                >
                  Retry
                </button>
              )}
            </div>
          </div>
        )}
        {catalogs.map(cat => (
          <div key={cat.name}>
            <button onClick={() => toggleCatalog(cat.name)} className="flex items-center gap-1 w-full px-3 py-1 hover:bg-muted text-left text-foreground">
              {expanded[cat.name] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Database size={12} className="text-primary" />
              <span>{cat.name}</span>
            </button>
            {loadingKeys.has(cat.name) && <div className="pl-8 py-1"><LoadingSpinner size={12} /></div>}
            {treeErrors[cat.name] && <div className="pl-8 py-1 text-red-400 text-[11px]">{treeErrors[cat.name]}</div>}
            {expanded[cat.name] && schemas[cat.name]?.map(sch => {
              const schKey = `${cat.name}.${sch.name}`;
              return (
              <div key={sch.name}>
                <button onClick={() => toggleSchema(cat.name, sch.name)} className="flex items-center gap-1 w-full pl-6 pr-3 py-1 hover:bg-muted text-left text-foreground">
                  {expanded[schKey] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <Folder size={12} className="text-primary" />
                  <span className="flex-1">{sch.name}</span>
                  {sch.external_use_schema != null && (
                    sch.external_use_schema
                      ? <ShieldCheck size={12} className="text-status-success shrink-0" title="EXTERNAL_USE_SCHEMA granted" />
                      : <ShieldOff size={12} className="text-muted-foreground/50 shrink-0" title="No external access grant" />
                  )}
                </button>
                {/* EUS grant/revoke controls (T88) — shown when schema is expanded */}
                {expanded[schKey] && sch.external_use_schema != null && (
                  <div className="pl-10 pr-3 py-1 flex items-center gap-2 text-[11px]">
                    {eusLoading.has(schKey) ? (
                      <LoadingSpinner size={10} />
                    ) : sch.external_use_schema ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRevokeEus(cat.name, sch.name); }}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-border text-muted-foreground hover:text-status-warning hover:border-status-warning transition-colors"
                        title="Revoke EXTERNAL USE SCHEMA"
                      >
                        <Lock size={11} />
                        <span>Revoke External Use</span>
                      </button>
                    ) : (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleGrantEus(cat.name, sch.name); }}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-border text-muted-foreground hover:text-status-success hover:border-status-success transition-colors"
                        title="Grant EXTERNAL USE SCHEMA"
                      >
                        <Unlock size={11} />
                        <span>Grant External Use</span>
                      </button>
                    )}
                    <span className="text-muted-foreground/60 italic" title="Only this permission is managed by Delta Router. All other permissions are managed in the Databricks workspace.">
                      Only permission managed by Delta Router
                    </span>
                  </div>
                )}
                {loadingKeys.has(`${cat.name}.${sch.name}`) && <div className="pl-12 py-1"><LoadingSpinner size={12} /></div>}
                {treeErrors[`${cat.name}.${sch.name}`] && <div className="pl-12 py-1 text-red-400 text-[11px]">{treeErrors[`${cat.name}.${sch.name}`]}</div>}
                {expanded[`${cat.name}.${sch.name}`] && tables[`${cat.name}.${sch.name}`]?.map(tbl => (
                  <button
                    key={tbl.name}
                    onClick={() => handleTableClick(tbl)}
                    className={`flex items-center gap-1 w-full pl-10 pr-3 py-1 hover:bg-muted text-left ${
                      selectedTable?.full_name === tbl.full_name ? "bg-muted" : ""
                    }`}
                  >
                    <div className={`w-1 h-4 rounded-sm mr-1 ${tableBarColor(tbl)}`} title={tableBarTitle(tbl)} />
                    <Table2 size={12} className="text-muted-foreground" />
                    <span className="text-foreground">{tbl.name}</span>
                  </button>
                ))}
              </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Table Detail */}
      {selectedTable && (
        <div className="border-t border-panel-border p-3 overflow-y-auto text-[12px] max-h-[50%]">
          <h4 className="font-semibold text-[13px] mb-2 text-foreground">{selectedTable.full_name}</h4>
          <div className="space-y-1 text-muted-foreground">
            <p><span className="font-medium text-foreground">Type:</span> {selectedTable.table_type}</p>
            {selectedTable.data_source_format && (
              <p>
                <span className="font-medium text-foreground">Format:</span>{" "}
                <span className={
                  FOREIGN_FORMATS.has(selectedTable.data_source_format) ? "text-red-500 font-medium" : ""
                }>
                  {selectedTable.data_source_format}
                </span>
              </p>
            )}
            <p><span className="font-medium text-foreground">Size:</span> {formatBytes(selectedTable.size_bytes)}</p>
            <p><span className="font-medium text-foreground">Rows:</span> {formatNumber(selectedTable.row_count)}</p>
            {selectedTable.storage_location && <p><span className="font-medium text-foreground">Location:</span> {selectedTable.storage_location}</p>}
            <p>
              <span className="font-medium text-foreground">DuckDB Readable:</span>{" "}
              {selectedTable.table_type === "FOREIGN"
                ? <span className="text-red-500">No — Foreign table (Databricks only)</span>
                : selectedTable.external_engine_read_support
                  ? <span className="text-status-success">Yes</span>
                  : <span className="text-status-warning">No — {selectedTable.read_support_reason}</span>}
            </p>
            {(() => {
              const parts = selectedTable.full_name.split(".");
              if (parts.length >= 2) {
                const catalogName = parts[0];
                const schemaList = schemas[catalogName];
                const sch = schemaList?.find(s => s.name === parts[1]);
                if (sch?.external_use_schema != null) {
                  return (
                    <p>
                      <span className="font-medium text-foreground">Schema External Access:</span>{" "}
                      {sch.external_use_schema
                        ? <span className="text-status-success flex items-center gap-1 inline-flex"><ShieldCheck size={11} /> Granted</span>
                        : <span className="text-muted-foreground flex items-center gap-1 inline-flex"><ShieldOff size={11} /> Not granted</span>}
                    </p>
                  );
                }
              }
              return null;
            })()}
          </div>
          <div className="mt-2">
            <p className="font-medium text-foreground mb-1">Columns</p>
            <div className="space-y-0.5">
              {selectedTable.columns.map(c => (
                <div key={c.name} className="flex justify-between text-muted-foreground">
                  <span className="font-mono">{c.name}</span>
                  <span className="font-mono text-[11px]">{c.type_text}</span>
                </div>
              ))}
            </div>
          </div>
          <button
            onClick={() => handleLoadSample(selectedTable)}
            className="mt-2 px-3 py-1 bg-primary text-primary-foreground rounded text-[12px] font-medium"
          >
            Load Sample Query
          </button>
        </div>
      )}
    </div>
  );
};
