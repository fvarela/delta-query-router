import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { RunMode, PanelMode, QueryExecutionResult, Workspace, DatabricksSettings, EngineCatalogEntry, Model, RoutingSettings, StorageLatencyProbe } from "../types";
import { mockApi } from "@/mocks/api";
import { api } from "@/lib/api";

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

  // Workspaces — metadata (id, name, url) in localStorage; PAT tokens never stored client-side
  const WORKSPACES_KEY = "delta_router_workspaces";

  const loadWorkspacesFromStorage = (): Workspace[] => {
    try {
      const raw = localStorage.getItem(WORKSPACES_KEY);
      if (!raw) return [];
      const stored = JSON.parse(raw) as Array<{ id: string; name: string; url: string }>;
      return stored.map(s => ({ id: s.id, name: s.name, url: s.url, token: null, connected: false, username: null }));
    } catch {
      return [];
    }
  };

  const saveWorkspacesToStorage = (ws: Workspace[]) => {
    // Only persist non-sensitive metadata — never tokens
    const toStore = ws.map(w => ({ id: w.id, name: w.name, url: w.url }));
    localStorage.setItem(WORKSPACES_KEY, JSON.stringify(toStore));
  };

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const connectedWorkspace = workspaces.find(w => w.connected) ?? null;

  const reloadWorkspaces = useCallback(async () => {
    // 1. Load workspace list from localStorage (name + URL only, no tokens)
    const stored = loadWorkspacesFromStorage();

    // 2. Check backend for active connection
    try {
      const settings = await api.get<DatabricksSettings>("/api/settings/databricks");
      if (settings.configured && settings.host) {
        // Find workspace matching the connected host
        const matchIdx = stored.findIndex(w => w.url === settings.host);
        if (matchIdx >= 0) {
          stored[matchIdx].connected = true;
          stored[matchIdx].username = settings.username ?? null;
        } else {
          // Backend is configured but no matching workspace in localStorage — create synthetic entry
          stored.push({
            id: crypto.randomUUID(),
            name: settings.host.replace(/^https?:\/\//, "").split(".")[0],
            url: settings.host,
            token: null,
            connected: true,
            username: settings.username ?? null,
          });
          // Persist the new entry
          saveWorkspacesToStorage(stored);
        }
      }
    } catch {
      // Backend unreachable or user not logged in — just show stored workspaces as disconnected
    }

    setWorkspaces(stored);
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
  const [routingSettings, setRoutingSettings] = useState<RoutingSettings>({ latency_weight: 0.5, cost_weight: 0.5, running_bonus_duckdb: 0.05, running_bonus_databricks: 0.15 });

  const updateRoutingSettings = useCallback(async (settings: Partial<RoutingSettings>) => {
    const updated = await api.put<RoutingSettings>("/api/routing/settings", settings);
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

  // Initial data load
  useEffect(() => {
    reloadWorkspaces();
    reloadEngines();
    reloadModels();
    reloadStorageProbes();
    api.get<RoutingSettings>("/api/routing/settings").then(setRoutingSettings).catch(() => {});
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
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
