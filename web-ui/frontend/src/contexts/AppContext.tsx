import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { RunMode, PanelMode, QueryExecutionResult, Workspace, EngineCatalogEntry, Model, RoutingSettings, StorageLatencyProbe, StorageAccountStatus, AzureStorageConfig } from "../types";
import { mockApi } from "@/mocks/api";

// ---- App Context ----
interface AppContextType {
  // Editor
  editorSql: string;
  setEditorSql: (s: string) => void;
  queryResult: QueryExecutionResult | null;
  setQueryResult: (r: QueryExecutionResult | null) => void;
  collectionContext: { collectionName: string; queryLabel: string; originalSql: string } | null;
  setCollectionContext: (c: { collectionName: string; queryLabel: string; originalSql: string } | null) => void;
  refreshCollections: number;
  triggerRefreshCollections: () => void;

  // Active collection (set by CollectionsPanel when a collection is open)
  activeCollectionId: number | null;
  setActiveCollectionId: (id: number | null) => void;

  // Workspaces
  workspaces: Workspace[];
  setWorkspaces: (ws: Workspace[]) => void;
  connectedWorkspace: Workspace | null; // derived — the one with connected === true
  reloadWorkspaces: () => Promise<void>;

  // Engines
  engines: EngineCatalogEntry[];
  reloadEngines: () => Promise<void>;
  /** IDs of engines selected for multi-engine routing (checkboxes) */
  enabledEngineIds: Set<number>;
  toggleEngineEnabled: (id: number) => void;
  setAllEnginesEnabled: (ids: number[]) => void;
  /** ID of the single engine selected via radio button */
  singleEngineId: number | null;
  setSingleEngineId: (id: number | null) => void;

  // Run mode (derived from engine selection count — not settable directly)
  runMode: RunMode;

  // Panel mode (Run vs Train)
  panelMode: PanelMode;
  setPanelMode: (mode: PanelMode) => void;

  // Active model
  activeModelId: number | null;
  setActiveModelId: (id: number | null) => void;
  models: Model[];
  reloadModels: () => Promise<void>;

  // Routing settings (ODQ-10)
  routingSettings: RoutingSettings;
  updateRoutingSettings: (settings: Partial<RoutingSettings>) => Promise<void>;

  // Storage latency probes (ODQ-9)
  storageProbes: StorageLatencyProbe[];
  reloadStorageProbes: () => Promise<void>;
  runStorageProbes: () => Promise<void>;
  probesRunning: boolean;

  // Storage account authorization (ODQ-12)
  storageAccounts: StorageAccountStatus[];
  azureStorageConfig: AzureStorageConfig;
  reloadStorageAccounts: () => Promise<void>;
  reloadAzureStorageConfig: () => Promise<void>;
  testStorageConnectivity: (storageAccount?: string) => Promise<void>;
  storageTestRunning: boolean;
  openSpModal: boolean;
  setOpenSpModal: (open: boolean) => void;
}

const AppContext = createContext<AppContextType>(null!);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Editor state
  const [editorSql, setEditorSql] = useState("");
  const [queryResult, setQueryResult] = useState<QueryExecutionResult | null>(null);
  const [collectionContext, setCollectionContext] = useState<{ collectionName: string; queryLabel: string; originalSql: string } | null>(null);
  const [refreshCollections, setRefresh] = useState(0);
  const triggerRefreshCollections = useCallback(() => setRefresh(p => p + 1), []);
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);

  // Workspaces
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const connectedWorkspace = workspaces.find(w => w.connected) ?? null;

  const reloadWorkspaces = useCallback(async () => {
    const ws = await mockApi.getWorkspaces();
    setWorkspaces(ws);
  }, []);

  // Engines
  const [engines, setEngines] = useState<EngineCatalogEntry[]>([]);
  const [enabledEngineIds, setEnabledEngineIds] = useState<Set<number>>(new Set());
  const [singleEngineId, setSingleEngineId] = useState<number | null>(null);

  const reloadEngines = useCallback(async () => {
    const e = await mockApi.getEngineCatalog();
    setEngines(e);
    // Default: all enabled engines are checked
    setEnabledEngineIds(new Set(e.filter(x => x.enabled).map(x => x.id)));
    // Default single engine: first enabled engine
    const first = e.find(x => x.enabled);
    if (first && singleEngineId === null) setSingleEngineId(first.id);
  }, [singleEngineId]);

  const toggleEngineEnabled = useCallback((id: number) => {
    setEnabledEngineIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const setAllEnginesEnabled = useCallback((ids: number[]) => {
    setEnabledEngineIds(new Set(ids));
  }, []);

  // Run mode — derived from how many *visible* engines are selected
  // (Databricks engines are hidden when no workspace is connected)
  const visibleEnabledCount = engines.filter(e => {
    if (!enabledEngineIds.has(e.id)) return false;
    if (e.engine_type === "databricks_sql" && !connectedWorkspace) return false;
    return true;
  }).length;
  const runMode: RunMode = visibleEnabledCount > 1 ? "multi" : "single";

  // Panel mode (Run vs Train)
  const [panelMode, setPanelModeRaw] = useState<PanelMode>("run");
  const [savedEngineIds, setSavedEngineIds] = useState<Set<number> | null>(null);

  const setPanelMode = useCallback((mode: PanelMode) => {
    if (mode === "train") {
      // Save current engine selection, then select all DuckDB + ephemeral Databricks
      setSavedEngineIds(new Set(enabledEngineIds));
      const trainEngineIds = engines
        .filter(e => e.engine_type === "duckdb" || e.engine_type === "databricks_sql")
        .map(e => e.id);
      setEnabledEngineIds(new Set(trainEngineIds));
    } else {
      // Restore previous engine selection
      if (savedEngineIds !== null) {
        setEnabledEngineIds(savedEngineIds);
        setSavedEngineIds(null);
      }
    }
    setPanelModeRaw(mode);
  }, [engines, enabledEngineIds, savedEngineIds]);

  // Models
  const [models, setModels] = useState<Model[]>([]);
  const [activeModelId, setActiveModelId] = useState<number | null>(null);

  const reloadModels = useCallback(async () => {
    const m = await mockApi.getModels();
    setModels(m);
    const active = m.find(x => x.is_active);
    if (active) setActiveModelId(active.id);
  }, []);

  // Routing settings (ODQ-10)
  const [routingSettings, setRoutingSettings] = useState<RoutingSettings>({ latency_weight: 0.5, cost_weight: 0.5, cost_estimation_mode: "formula", running_bonus_duckdb: 0.05, running_bonus_databricks: 0.15 });

  const updateRoutingSettings = useCallback(async (settings: Partial<RoutingSettings>) => {
    const updated = await mockApi.updateRoutingSettings(settings);
    setRoutingSettings(updated);
  }, []);

  // Storage latency probes (ODQ-9)
  const [storageProbes, setStorageProbes] = useState<StorageLatencyProbe[]>([]);
  const [probesRunning, setProbesRunning] = useState(false);

  const reloadStorageProbes = useCallback(async () => {
    const probes = await mockApi.getStorageLatencyProbes();
    setStorageProbes(probes);
  }, []);

  const runStorageProbes = useCallback(async () => {
    setProbesRunning(true);
    try {
      await mockApi.runStorageLatencyProbes();
      await reloadStorageProbes();
    } finally {
      setProbesRunning(false);
    }
  }, [reloadStorageProbes]);

  // Storage account authorization (ODQ-12)
  const [storageAccounts, setStorageAccounts] = useState<StorageAccountStatus[]>([]);
  const [azureStorageConfig, setAzureStorageConfig] = useState<AzureStorageConfig>({ configured: false, tenant_id: null, client_id: null });
  const [storageTestRunning, setStorageTestRunning] = useState(false);
  const [openSpModal, setOpenSpModal] = useState(false);

  const reloadAzureStorageConfig = useCallback(async () => {
    const cfg = await mockApi.getAzureStorageConfig();
    setAzureStorageConfig(cfg);
  }, []);

  const reloadStorageAccounts = useCallback(async () => {
    const accts = await mockApi.getStorageAccounts();
    setStorageAccounts(accts);
  }, []);

  const testStorageConnectivity = useCallback(async (storageAccount?: string) => {
    setStorageTestRunning(true);
    try {
      await mockApi.testStorageAccounts(storageAccount);
      await reloadStorageAccounts();
    } finally {
      setStorageTestRunning(false);
    }
  }, [reloadStorageAccounts]);

  // Reload storage accounts when workspace connection changes
  // Storage accounts are discovered from Unity Catalog table metadata,
  // which is only available when connected to a Databricks workspace.
  useEffect(() => {
    if (connectedWorkspace) {
      reloadStorageAccounts();
    } else {
      setStorageAccounts([]);
    }
  }, [connectedWorkspace, reloadStorageAccounts]);

  // Initial data load
  useEffect(() => {
    reloadWorkspaces();
    reloadEngines();
    reloadModels();
    reloadStorageProbes();
    reloadAzureStorageConfig();
    mockApi.getRoutingSettings().then(setRoutingSettings);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AppContext.Provider value={{
      editorSql, setEditorSql, queryResult, setQueryResult,
      collectionContext, setCollectionContext,
      refreshCollections, triggerRefreshCollections,
      activeCollectionId, setActiveCollectionId,
      workspaces, setWorkspaces, connectedWorkspace, reloadWorkspaces,
      engines, reloadEngines, enabledEngineIds, toggleEngineEnabled, setAllEnginesEnabled,
      singleEngineId, setSingleEngineId,
      runMode,
      panelMode, setPanelMode,
      activeModelId, setActiveModelId, models, reloadModels,
      routingSettings, updateRoutingSettings,
      storageProbes, reloadStorageProbes, runStorageProbes, probesRunning,
      storageAccounts, azureStorageConfig, reloadStorageAccounts, reloadAzureStorageConfig,
      testStorageConnectivity, storageTestRunning, openSpModal, setOpenSpModal,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
