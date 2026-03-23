import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import { useApp } from "@/contexts/AppContext";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import type { CatalogInfo, SchemaInfo, TableInfo, StorageAccountStatus } from "@/types";
import { FOREIGN_FORMATS } from "@/types";
import { ChevronRight, ChevronDown, Folder, Table2, Database, ExternalLink, RefreshCw } from "lucide-react";

/** Three-color classification for the catalog tree indicator bar.
 *  Green  = DuckDB-readable (Delta / Iceberg) AND storage accessible
 *  Amber  = Databricks-only (native format but blocked, or VIEWs), OR DuckDB-readable but storage inaccessible
 *  Red    = Foreign / federated tables (always Databricks)
 */
const tableBarColor = (t: TableInfo, storageAccounts: StorageAccountStatus[]): string => {
  if (t.table_type === "FOREIGN") return "bg-red-500";
  if (t.external_engine_read_support) {
    // Check if the storage account for this table is inaccessible
    const acct = findStorageAccount(t, storageAccounts);
    if (acct && acct.status === "inaccessible") return "bg-status-warning";
    return "bg-status-success";
  }
  return "bg-status-warning";
};

/** Tooltip text for the bar color */
const tableBarTitle = (t: TableInfo, storageAccounts: StorageAccountStatus[]): string => {
  if (t.table_type === "FOREIGN") return "Foreign / federated — Databricks only";
  if (t.external_engine_read_support) {
    const acct = findStorageAccount(t, storageAccounts);
    if (acct && acct.status === "inaccessible") return "DuckDB readable but storage inaccessible";
    return "DuckDB readable";
  }
  return "Databricks only";
};

/** Find the storage account status matching a table's storage_location */
const findStorageAccount = (t: TableInfo, storageAccounts: StorageAccountStatus[]): StorageAccountStatus | undefined => {
  if (!t.storage_location) return undefined;
  return storageAccounts.find(a => t.storage_location!.includes(a.storage_account));
};

const formatBytes = (b: number | null) => {
  if (!b) return "-";
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(1)} GB`;
};

const formatNumber = (n: number | null) => n == null ? "-" : n.toLocaleString();

export const CatalogBrowser: React.FC = () => {
  const { connectedWorkspace, setEditorSql, setCollectionContext, storageAccounts, testStorageConnectivity, storageTestRunning, setOpenSpModal } = useApp();
  const [catalogs, setCatalogs] = useState<CatalogInfo[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [schemas, setSchemas] = useState<Record<string, SchemaInfo[]>>({});
  const [tables, setTables] = useState<Record<string, TableInfo[]>>({});
  const [loadingKeys, setLoadingKeys] = useState<Set<string>>(new Set());
  const [selectedTable, setSelectedTable] = useState<TableInfo | null>(null);

  useEffect(() => {
    if (!connectedWorkspace) {
      setCatalogs([]);
      return;
    }
    setLoadingKeys(new Set(["catalogs"]));
    mockApi.getCatalogs().then(c => {
      setCatalogs(c);
      setLoadingKeys(prev => { const n = new Set(prev); n.delete("catalogs"); return n; });
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
      const s = await mockApi.getSchemas(catalog);
      setSchemas(prev => ({ ...prev, [catalog]: s }));
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
      const t = await mockApi.getTables(catalog, schema);
      setTables(prev => ({ ...prev, [key]: t }));
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
        <span className="font-semibold text-foreground">Catalog Browser</span>
      </div>
      <div className="flex-1 overflow-y-auto text-[12px]">
        {loadingKeys.has("catalogs") && <div className="p-3"><LoadingSpinner /></div>}
        {catalogs.map(cat => (
          <div key={cat.name}>
            <button onClick={() => toggleCatalog(cat.name)} className="flex items-center gap-1 w-full px-3 py-1 hover:bg-muted text-left text-foreground">
              {expanded[cat.name] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Database size={12} className="text-primary" />
              <span>{cat.name}</span>
            </button>
            {loadingKeys.has(cat.name) && <div className="pl-8 py-1"><LoadingSpinner size={12} /></div>}
            {expanded[cat.name] && schemas[cat.name]?.map(sch => (
              <div key={sch.name}>
                <button onClick={() => toggleSchema(cat.name, sch.name)} className="flex items-center gap-1 w-full pl-6 pr-3 py-1 hover:bg-muted text-left text-foreground">
                  {expanded[`${cat.name}.${sch.name}`] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <Folder size={12} className="text-primary" />
                  <span>{sch.name}</span>
                </button>
                {loadingKeys.has(`${cat.name}.${sch.name}`) && <div className="pl-12 py-1"><LoadingSpinner size={12} /></div>}
                {expanded[`${cat.name}.${sch.name}`] && tables[`${cat.name}.${sch.name}`]?.map(tbl => (
                  <button
                    key={tbl.name}
                    onClick={() => handleTableClick(tbl)}
                    className={`flex items-center gap-1 w-full pl-10 pr-3 py-1 hover:bg-muted text-left ${
                      selectedTable?.full_name === tbl.full_name ? "bg-muted" : ""
                    }`}
                  >
                    <div className={`w-1 h-4 rounded-sm mr-1 ${tableBarColor(tbl, storageAccounts)}`} title={tableBarTitle(tbl, storageAccounts)} />
                    <Table2 size={12} className="text-muted-foreground" />
                    <span className="text-foreground">{tbl.name}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Table Detail */}
      {selectedTable && (
        <div className="border-t border-panel-border p-3 overflow-y-auto text-[11px] max-h-[50%]">
          <h4 className="font-semibold text-[12px] mb-2 text-foreground">{selectedTable.full_name}</h4>
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
            {/* Storage Access (ODQ-12) */}
            {selectedTable.storage_location && (() => {
              const acct = findStorageAccount(selectedTable, storageAccounts);
              if (!acct) return null;
              return (
                <div className="mt-1 pt-1 border-t border-border/50">
                  <p className="flex items-center gap-1">
                    <span className="font-medium text-foreground">Storage Access:</span>
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      acct.status === "accessible" ? "bg-status-success"
                      : acct.status === "inaccessible" ? "bg-status-error"
                      : "bg-muted-foreground/40"
                    }`} />
                    {acct.status === "accessible" && <span className="text-status-success">Accessible</span>}
                    {acct.status === "inaccessible" && <span className="text-status-error">Inaccessible</span>}
                    {acct.status === "untested" && <span className="text-muted-foreground">Untested</span>}
                  </p>
                  <p className="text-[10px] font-mono text-muted-foreground mt-0.5">{acct.storage_account}</p>
                  {acct.status === "inaccessible" && acct.failure_reason && (
                    <p className="text-[10px] text-status-error mt-0.5">{acct.failure_reason}</p>
                  )}
                  <div className="flex items-center gap-2 mt-1">
                    {acct.status === "inaccessible" && acct.azure_portal_link && (
                      <a
                        href={acct.azure_portal_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-[10px] text-primary hover:text-primary/80"
                      >
                        Fix in Azure Portal <ExternalLink size={9} />
                      </a>
                    )}
                    {acct.status !== "accessible" && (
                      <button
                        onClick={() => testStorageConnectivity(acct.storage_account)}
                        disabled={storageTestRunning}
                        className="inline-flex items-center gap-0.5 text-[10px] text-primary hover:text-primary/80 disabled:opacity-40"
                      >
                        <RefreshCw size={9} /> Test
                      </button>
                    )}
                    {!acct.status || acct.status === "untested" ? (
                      <button
                        onClick={() => setOpenSpModal(true)}
                        className="text-[10px] text-primary hover:text-primary/80"
                      >
                        Configure SP
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })()}
          </div>
          <div className="mt-2">
            <p className="font-medium text-foreground mb-1">Columns</p>
            <div className="space-y-0.5">
              {selectedTable.columns.map(c => (
                <div key={c.name} className="flex justify-between text-muted-foreground">
                  <span className="font-mono">{c.name}</span>
                  <span className="font-mono text-[10px]">{c.type_text}</span>
                </div>
              ))}
            </div>
          </div>
          <button
            onClick={() => handleLoadSample(selectedTable)}
            className="mt-2 px-3 py-1 bg-primary text-primary-foreground rounded text-[11px] font-medium"
          >
            Load Sample Query
          </button>
        </div>
      )}
    </div>
  );
};
