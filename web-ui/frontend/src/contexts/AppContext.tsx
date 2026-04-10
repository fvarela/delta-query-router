import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from "react";
import type { RunMode, RoutingMode, PanelMode, LeftPanelTab, RoutingConfig, RoutingProfile, WorkspaceBinding, WarehouseMapping, DiscoveredWarehouse, QueryExecutionResult, Workspace, Warehouse, DatabricksSettings, EngineCatalogEntry, Model, RoutingSettings, RoutingSettingsResponse, StorageLatencyProbe, BenchmarkDefinition } from "../types";
import { api } from "@/lib/api";
import { isMockMode } from "@/lib/mockMode";
import { MOCK_ENGINES, MOCK_MODELS, MOCK_BENCHMARK_DEFINITIONS, MOCK_ROUTING_PROFILES, MOCK_DISCOVERED_WAREHOUSES, MOCK_WORKSPACES } from "@/mocks/engineSetupData";

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

  // Warehouses
  warehouses: Warehouse[];
  selectedWarehouseId: string | null;
  warehousesLoading: boolean;
  reloadWarehouses: () => Promise<void>;
  selectWarehouse: (id: string | null) => Promise<void>;
  clearWarehouses: () => void;

  // Engines
  engines: EngineCatalogEntry[];
  reloadEngines: () => Promise<void>;
  /** IDs of engines selected for multi-engine routing (checkboxes in Smart Routing mode) */
  enabledEngineIds: Set<string>;
  toggleEngineEnabled: (id: string) => void;
  setAllEnginesEnabled: (ids: string[]) => void;
  /** ID of the single engine selected in Single Engine mode */
  singleEngineId: string | null;
  setSingleEngineId: (id: string | null) => void;

  /** Scale a DuckDB engine (start/stop) */
  scaleEngine: (engineId: string, replicas: number) => Promise<void>;
  scalingEngineIds: Set<string>;

  // Routing mode (user-selected: "single", "smart", or "benchmark")
  routingMode: RoutingMode;
  setRoutingMode: (mode: RoutingMode) => void;

  /** IDs of engines selected for benchmarking (checkboxes in Benchmark mode) */
  benchmarkEngineIds: Set<string>;
  toggleBenchmarkEngine: (id: string) => void;
  setBenchmarkEngines: (ids: string[]) => void;

  // Run mode (derived from routing mode + selection — kept for backward compat)
  runMode: RunMode;

  // Panel mode (Run vs Train)
  panelMode: PanelMode;
  setPanelMode: (mode: PanelMode) => void;

  // Active model
  activeModelId: number | null;
  setActiveModelId: (id: number | null) => void;
  models: Model[];
  reloadModels: () => Promise<void>;
  deleteModel: (id: number) => Promise<void>;
  activateModel: (id: number) => Promise<void>;
  deactivateModel: (id: number) => Promise<void>;
  createModel: (linkedEngines: string[], trainingCollectionIds: number[]) => Promise<Model>;

  // Routing settings (ODQ-10)
  routingSettings: RoutingSettings;
  updateRoutingSettings: (settings: Partial<RoutingSettings>) => Promise<void>;

  // Storage latency probes (ODQ-9)
  storageProbes: StorageLatencyProbe[];
  reloadStorageProbes: () => Promise<void>;
  runStorageProbes: () => Promise<void>;
  probesRunning: boolean;

  // Benchmark definitions (Phase 15 — Collections panel runs)
  benchmarkDefinitions: BenchmarkDefinition[];
  reloadBenchmarkDefinitions: () => Promise<void>;

  // Left panel tab (lifted so other panels can switch it)
  leftPanelTab: LeftPanelTab;
  setLeftPanelTab: (tab: LeftPanelTab) => void;

  // Saved routing config (persistent settings — Round 8)
  savedRoutingConfig: RoutingConfig;
  hasUnsavedChanges: boolean;
  saveRoutingConfig: () => Promise<void>;
  rollbackRoutingConfig: () => void;

  // Routing profiles (persistent named configs — Round 13)
  routingProfiles: RoutingProfile[];
  activeProfileId: number | null;
  activeProfileName: string | null;
  loadProfile: (id: number) => void;
  saveProfile: () => Promise<void>;
  saveProfileAs: (name: string) => Promise<void>;
  deleteProfile: (id: number) => Promise<void>;
  setDefaultProfile: (id: number) => Promise<void>;
  clearActiveProfile: () => void;

  // Workspace binding for current profile (Round 16 → Round 17: implicit, derived from warehouse mappings)
  profileWorkspaceBinding: WorkspaceBinding | null;
  /** Clear workspace binding and all warehouse mappings (unlink from workspace) */
  unlinkProfileWorkspace: () => void;

  // Warehouse mappings for current routing config (Round 16)
  warehouseMappings: WarehouseMapping[];
  setWarehouseMapping: (engineId: string, warehouseId: string | null, warehouseName: string | null) => void;

  // Discovered warehouses from the bound workspace (Round 16)
  discoveredWarehouses: DiscoveredWarehouse[];
  reloadDiscoveredWarehouses: () => Promise<void>;
}

const AppContext = createContext<AppContextType>(null!);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const mock = isMockMode();

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

  const [workspaces, setWorkspaces] = useState<Workspace[]>(mock ? [...MOCK_WORKSPACES] : []);
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

  // Warehouses — fetched from real API when a workspace is connected
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<string | null>(null);
  const [warehousesLoading, setWarehousesLoading] = useState(false);

  const reloadWarehouses = useCallback(async () => {
    setWarehousesLoading(true);
    try {
      const list = await api.get<Warehouse[]>("/api/databricks/warehouses");
      setWarehouses(list);

      // If backend already has a warehouse_id selected, pre-select it (if it still exists in the list)
      try {
        const settings = await api.get<DatabricksSettings>("/api/settings/databricks");
        if (settings.warehouse_id && list.some(w => w.id === settings.warehouse_id)) {
          setSelectedWarehouseId(settings.warehouse_id);
        } else if (settings.warehouse_id && !list.some(w => w.id === settings.warehouse_id)) {
          // Previously selected warehouse no longer exists — clear selection
          setSelectedWarehouseId(null);
        }
      } catch {
        // Settings endpoint failed — don't change selection
      }
    } catch {
      // Workspace not connected or API error — clear warehouse list
      setWarehouses([]);
    } finally {
      setWarehousesLoading(false);
    }
  }, []);

  const selectWarehouse = useCallback(async (id: string | null) => {
    if (!id) {
      setSelectedWarehouseId(null);
      return;
    }
    try {
      await api.put("/api/settings/warehouse", { warehouse_id: id });
      setSelectedWarehouseId(id);
    } catch {
      // PUT failed — don't update local state
    }
  }, []);

  const clearWarehouses = useCallback(() => {
    setWarehouses([]);
    setSelectedWarehouseId(null);
  }, []);

  // Engines
  const [engines, setEngines] = useState<EngineCatalogEntry[]>(mock ? MOCK_ENGINES : []);
  const [enabledEngineIds, setEnabledEngineIds] = useState<Set<string>>(
    mock ? new Set(MOCK_MODELS[0].linked_engines) : new Set()
  );
  const [singleEngineId, setSingleEngineId] = useState<string | null>(
    mock ? (MOCK_ENGINES.find(e => e.runtime_state === "running")?.id ?? null) : null
  );
  const [scalingEngineIds, setScalingEngineIds] = useState<Set<string>>(new Set());

  const reloadEngines = useCallback(async () => {
    if (mock) {
      setEngines(MOCK_ENGINES);
      setEnabledEngineIds(new Set(MOCK_ENGINES.filter(x => x.enabled).map(x => x.id)));
      return;
    }
    // Fetch engines from real backend API (DuckDB worker health + Databricks warehouses)
    try {
      const e = await api.get<EngineCatalogEntry[]>("/api/engines");
      setEngines(e);
      // Default: all enabled engines are checked
      setEnabledEngineIds(new Set(e.filter(x => x.enabled).map(x => x.id)));
      // Default single engine: first enabled engine
      const first = e.find(x => x.enabled);
      if (first && singleEngineId === null) setSingleEngineId(first.id);
    } catch {
      // Fallback: keep whatever engines we have
    }
  }, [mock, singleEngineId]);

  const scaleEngine = useCallback(async (engineId: string, replicas: number) => {
    setScalingEngineIds(prev => new Set(prev).add(engineId));
    try {
      await api.post(`/api/engines/${engineId}/scale`, { replicas });
      // Wait a moment for K8s to react, then reload engine status
      await new Promise(r => setTimeout(r, 2000));
      await reloadEngines();
    } finally {
      setScalingEngineIds(prev => {
        const next = new Set(prev);
        next.delete(engineId);
        return next;
      });
    }
  }, [reloadEngines]);

  const toggleEngineEnabled = useCallback((id: string) => {
    setEnabledEngineIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const setAllEnginesEnabled = useCallback((ids: string[]) => {
    setEnabledEngineIds(new Set(ids));
  }, []);

  // Routing mode — user-selected: "single" (no model) or "smart" (model-driven) or "benchmark" (multi-engine, no model/profile)
  const [routingMode, setRoutingModeRaw] = useState<RoutingMode>(mock ? "smart" : "single");

  // Benchmark engine selection — separate from enabledEngineIds (which is for Smart Routing)
  const [benchmarkEngineIds, setBenchmarkEngineIdsRaw] = useState<Set<string>>(new Set());

  const toggleBenchmarkEngine = useCallback((id: string) => {
    setBenchmarkEngineIdsRaw(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const setBenchmarkEngines = useCallback((ids: string[]) => {
    setBenchmarkEngineIdsRaw(new Set(ids));
  }, []);

  // Run mode — derived from routingMode for backward compat
  const runMode: RunMode = routingMode === "smart" ? "multi" : "single";

  // In single mode, derive the single engine ID from user selection
  const derivedSingleEngineId = singleEngineId;

  // Panel mode (Run vs Train)
  const [panelMode, setPanelModeRaw] = useState<PanelMode>("run");
  const [savedEngineIds, setSavedEngineIds] = useState<Set<string> | null>(null);

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
  const [models, setModels] = useState<Model[]>(mock ? MOCK_MODELS : []);
  const [activeModelId, setActiveModelId] = useState<number | null>(mock ? 1 : null);

  const reloadModels = useCallback(async () => {
    if (mock) {
      setModels(MOCK_MODELS);
      const active = MOCK_MODELS.find(x => x.is_active);
      if (active) setActiveModelId(active.id);
      return;
    }
    try {
      const m = await api.get<Model[]>("/api/models");
      setModels(m);
      const active = m.find(x => x.is_active);
      if (active) setActiveModelId(active.id);
    } catch {
      // API error — keep current state
    }
  }, [mock]);

  // Model CRUD operations
  const deleteModel = useCallback(async (id: number) => {
    if (mock) {
      setModels(prev => prev.filter(m => m.id !== id));
      if (activeModelId === id) setActiveModelId(null);
      return;
    }
    await api.del(`/api/models/${id}`);
    if (activeModelId === id) setActiveModelId(null);
    await reloadModels();
  }, [mock, activeModelId, reloadModels]);

  const activateModel = useCallback(async (id: number) => {
    if (mock) {
      setModels(prev => prev.map(m => ({
        ...m,
        is_active: m.id === id,
      })));
      setActiveModelId(id);
      return;
    }
    await api.post(`/api/models/${id}/activate`);
    setActiveModelId(id);
    await reloadModels();
  }, [mock, reloadModels]);

  const deactivateModel = useCallback(async (id: number) => {
    if (mock) {
      setModels(prev => prev.map(m =>
        m.id === id ? { ...m, is_active: false } : m
      ));
      if (activeModelId === id) setActiveModelId(null);
      return;
    }
    await api.post(`/api/models/${id}/deactivate`);
    if (activeModelId === id) setActiveModelId(null);
    await reloadModels();
  }, [mock, activeModelId, reloadModels]);

  // Routing settings (ODQ-10)
  const [routingSettings, setRoutingSettings] = useState<RoutingSettings>({ fit_weight: 0.5, cost_weight: 0.5, running_bonus_duckdb: 0.05, running_bonus_databricks: 0.15 });

  const updateRoutingSettings = useCallback(async (settings: Partial<RoutingSettings>) => {
    if (mock) {
      setRoutingSettings(prev => ({ ...prev, ...settings }));
      return;
    }
    const updated = await api.put<RoutingSettings>("/api/routing/settings", settings);
    setRoutingSettings(updated);
  }, [mock]);

  // Storage latency probes (ODQ-9)
  const [storageProbes, setStorageProbes] = useState<StorageLatencyProbe[]>([]);
  const [probesRunning, setProbesRunning] = useState(false);

  const reloadStorageProbes = useCallback(async () => {
    const probes = await api.get<StorageLatencyProbe[]>('/api/latency-probes');
    setStorageProbes(probes);
  }, []);

  const runStorageProbes = useCallback(async () => {
    setProbesRunning(true);
    try {
      await api.post<{ probes: StorageLatencyProbe[] }>('/api/latency-probes/run', {}).then(r => r.probes);
      await reloadStorageProbes();
    } finally {
      setProbesRunning(false);
    }
  }, [reloadStorageProbes]);

  // Left panel tab (lifted so center panel can switch it)
  const [leftPanelTab, setLeftPanelTab] = useState<LeftPanelTab>("catalog");

  // Saved routing config (DB-persisted state — Round 8/9/12)
  // This represents the last configuration persisted to the backend database.
  // CurrentSettings is a live view of the working state; Save persists to DB,
  // Rollback reverts to the DB-persisted snapshot.
  const [savedRoutingConfig, setSavedRoutingConfig] = useState<RoutingConfig>(() => {
    if (mock) {
      // Load default profile's config
      const defaultProfile = MOCK_ROUTING_PROFILES.find(p => p.is_default);
      if (defaultProfile) return { ...defaultProfile.config };
      return {
        routingMode: "smart",
        singleEngineId: MOCK_ENGINES.find(e => e.enabled)?.id ?? null,
        activeModelId: 1,
        enabledEngineIds: MOCK_MODELS[0].linked_engines,
        routingPriority: 0.5,
        workspaceBinding: null,
        warehouseMappings: [],
      };
    }
    return { routingMode: "single", singleEngineId: null, activeModelId: null, enabledEngineIds: [], routingPriority: 0.5, workspaceBinding: null, warehouseMappings: [] };
  });

  // Routing profiles (persistent named configs — Round 13)
  const [routingProfiles, setRoutingProfiles] = useState<RoutingProfile[]>(
    mock ? [...MOCK_ROUTING_PROFILES] : []
  );
  const [activeProfileId, setActiveProfileId] = useState<number | null>(() => {
    if (mock) {
      const defaultProfile = MOCK_ROUTING_PROFILES.find(p => p.is_default);
      return defaultProfile?.id ?? null;
    }
    return null;
  });

  const activeProfileName = useMemo(() => {
    if (activeProfileId === null) return null;
    return routingProfiles.find(p => p.id === activeProfileId)?.name ?? null;
  }, [activeProfileId, routingProfiles]);

  // Reload profiles from backend (non-mock)
  const reloadProfiles = useCallback(async () => {
    if (mock) {
      setRoutingProfiles([...MOCK_ROUTING_PROFILES]);
      return;
    }
    try {
      const profiles = await api.get<RoutingProfile[]>("/api/routing/profiles");
      setRoutingProfiles(profiles);
    } catch {
      // API error — keep current state
    }
  }, [mock]);

  // UX #5/#7: Remember the profile that was active before entering benchmark mode, so we can restore it when leaving
  // MUST be declared after activeProfileId (uses it in setRoutingMode callback)
  const [preBenchmarkProfileId, setPreBenchmarkProfileId] = useState<number | null>(null);

  // When switching TO benchmark mode, save active profile and clear it (profiles don't apply).
  // When switching FROM benchmark mode, restore the saved profile and clear benchmark engine selection.
  const setRoutingMode = useCallback((mode: RoutingMode) => {
    if (mode === "benchmark") {
      // Save profile before entering benchmark mode (UX #5/#7)
      setPreBenchmarkProfileId(activeProfileId);
      setActiveProfileId(null);
    }
    if (routingMode === "benchmark" && mode !== "benchmark") {
      setBenchmarkEngineIdsRaw(new Set());
      // Restore profile when leaving benchmark mode (UX #5/#7)
      if (preBenchmarkProfileId !== null) {
        // Verify the profile still exists before restoring
        const profileExists = routingProfiles.some(p => p.id === preBenchmarkProfileId);
        if (profileExists) {
          // We use setTimeout to defer loadProfile until after mode has changed
          const savedId = preBenchmarkProfileId;
          setTimeout(() => {
            const profile = routingProfiles.find(p => p.id === savedId);
            if (profile) {
              setActiveProfileId(savedId);
              setSavedRoutingConfig({ ...profile.config });
              setSingleEngineId(profile.config.singleEngineId);
              setActiveModelId(profile.config.activeModelId);
              setEnabledEngineIds(new Set(profile.config.enabledEngineIds));
              setRoutingSettings(prev => ({
                ...prev,
                cost_weight: profile.config.routingPriority,
                fit_weight: 1 - profile.config.routingPriority,
              }));
              setProfileWorkspaceBinding(profile.config.workspaceBinding ?? null);
              setWarehouseMappings(profile.config.warehouseMappings ?? []);
            }
          }, 0);
        }
        setPreBenchmarkProfileId(null);
      }
    }
    setRoutingModeRaw(mode);
  }, [routingMode, activeProfileId, preBenchmarkProfileId, routingProfiles]);

  // Workspace binding for current profile (Round 16)
  // MUST be declared before loadProfile/saveProfile/hasUnsavedChanges which reference it
  const [profileWorkspaceBinding, setProfileWorkspaceBinding] = useState<WorkspaceBinding | null>(() => {
    if (mock) {
      const defaultProfile = MOCK_ROUTING_PROFILES.find(p => p.is_default);
      return defaultProfile?.config.workspaceBinding ?? null;
    }
    return null;
  });

  // Warehouse mappings for current routing config (Round 16)
  // MUST be declared before loadProfile/saveProfile/hasUnsavedChanges which reference it
  const [warehouseMappings, setWarehouseMappings] = useState<WarehouseMapping[]>(() => {
    if (mock) {
      const defaultProfile = MOCK_ROUTING_PROFILES.find(p => p.is_default);
      return defaultProfile?.config.warehouseMappings ?? [];
    }
    return [];
  });

  const setWarehouseMapping = useCallback((engineId: string, warehouseId: string | null, warehouseName: string | null) => {
    setWarehouseMappings(prev => {
      const existing = prev.findIndex(m => m.engineId === engineId);
      const newMapping: WarehouseMapping = { engineId, warehouseId, warehouseName };
      if (existing >= 0) {
        const next = [...prev];
        next[existing] = newMapping;
        return next;
      }
      return [...prev, newMapping];
    });
    // Round 17: Implicitly bind workspace when a warehouse is mapped
    // If user maps a Databricks engine to a warehouse, the profile becomes dependent on the current workspace
    if (warehouseId !== null && connectedWorkspace) {
      setProfileWorkspaceBinding({
        workspaceId: connectedWorkspace.id,
        workspaceName: connectedWorkspace.name,
        workspaceUrl: connectedWorkspace.url,
      });
    }
  }, [connectedWorkspace]);

  // Round 17: Unlink profile from workspace — clear binding AND all warehouse mappings
  const unlinkProfileWorkspace = useCallback(() => {
    setProfileWorkspaceBinding(null);
    setWarehouseMappings([]);
  }, []);

  // Discovered warehouses from the connected workspace (Round 16)
  const [discoveredWarehouses, setDiscoveredWarehouses] = useState<DiscoveredWarehouse[]>(
    mock ? MOCK_DISCOVERED_WAREHOUSES : []
  );

  const reloadDiscoveredWarehouses = useCallback(async () => {
    if (mock) {
      setDiscoveredWarehouses(MOCK_DISCOVERED_WAREHOUSES);
      return;
    }
    try {
      const list = await api.get<Warehouse[]>("/api/databricks/warehouses");
      // Map to DiscoveredWarehouse with engine matching from backend
      const discovered: DiscoveredWarehouse[] = list.map(w => ({
        id: w.id,
        name: w.name,
        state: w.state,
        cluster_size: w.cluster_size ?? "Unknown",
        warehouse_type: w.warehouse_type ?? "UNKNOWN",
        matchingEngineId: w.matched_engine_id ?? null,
      }));
      setDiscoveredWarehouses(discovered);
    } catch {
      setDiscoveredWarehouses([]);
    }
  }, [mock]);

  // Load a profile — apply its config to all working state
  const loadProfile = useCallback((id: number) => {
    const profile = routingProfiles.find(p => p.id === id);
    if (!profile) return;
    setActiveProfileId(id);
    setSavedRoutingConfig({ ...profile.config });
    // Apply config to working state
    setRoutingMode(profile.config.routingMode);
    setSingleEngineId(profile.config.singleEngineId);
    setActiveModelId(profile.config.activeModelId);
    setEnabledEngineIds(new Set(profile.config.enabledEngineIds));
    setRoutingSettings(prev => ({
      ...prev,
      cost_weight: profile.config.routingPriority,
      fit_weight: 1 - profile.config.routingPriority,
    }));
    // Restore workspace binding and warehouse mappings (Round 16)
    setProfileWorkspaceBinding(profile.config.workspaceBinding ?? null);
    setWarehouseMappings(profile.config.warehouseMappings ?? []);
  }, [routingProfiles]);

  // Save current config to the active profile (update in place)
  const saveProfile = useCallback(async () => {
    const currentConfig: RoutingConfig = {
      routingMode,
      singleEngineId,
      activeModelId,
      enabledEngineIds: [...enabledEngineIds],
      routingPriority: routingSettings.cost_weight,
      workspaceBinding: profileWorkspaceBinding,
      warehouseMappings: [...warehouseMappings],
    };
    if (activeProfileId !== null) {
      if (mock) {
        // Mock mode: update local state only
        setRoutingProfiles(prev => prev.map(p =>
          p.id === activeProfileId
            ? { ...p, config: currentConfig, updated_at: new Date().toISOString() }
            : p
        ));
      } else {
        // Real mode: persist to backend
        try {
          await api.put(`/api/routing/profiles/${activeProfileId}`, { config: currentConfig });
          await reloadProfiles();
        } catch {
          // API error — update local state as fallback
          setRoutingProfiles(prev => prev.map(p =>
            p.id === activeProfileId
              ? { ...p, config: currentConfig, updated_at: new Date().toISOString() }
              : p
          ));
        }
      }
    }
    setSavedRoutingConfig(currentConfig);
  }, [routingMode, singleEngineId, enabledEngineIds, routingSettings.cost_weight, activeModelId, activeProfileId, profileWorkspaceBinding, warehouseMappings, mock, reloadProfiles]);

  // Save As — create a new profile from current config
  const saveProfileAs = useCallback(async (name: string) => {
    const currentConfig: RoutingConfig = {
      routingMode,
      singleEngineId,
      activeModelId,
      enabledEngineIds: [...enabledEngineIds],
      routingPriority: routingSettings.cost_weight,
      workspaceBinding: profileWorkspaceBinding,
      warehouseMappings: [...warehouseMappings],
    };
    if (mock) {
      // Mock mode: create locally
      const newId = Math.max(0, ...routingProfiles.map(p => p.id)) + 1;
      const now = new Date().toISOString();
      const newProfile: RoutingProfile = {
        id: newId,
        name,
        is_default: false,
        config: currentConfig,
        created_at: now,
        updated_at: now,
      };
      setRoutingProfiles(prev => [...prev, newProfile]);
      setActiveProfileId(newId);
    } else {
      // Real mode: persist to backend
      try {
        const created = await api.post<RoutingProfile>("/api/routing/profiles", { name, config: currentConfig });
        await reloadProfiles();
        setActiveProfileId(created.id);
      } catch {
        // Fallback: create locally
        const newId = Math.max(0, ...routingProfiles.map(p => p.id)) + 1;
        const now = new Date().toISOString();
        const newProfile: RoutingProfile = { id: newId, name, is_default: false, config: currentConfig, created_at: now, updated_at: now };
        setRoutingProfiles(prev => [...prev, newProfile]);
        setActiveProfileId(newId);
      }
    }
    setSavedRoutingConfig(currentConfig);
  }, [routingMode, singleEngineId, enabledEngineIds, routingSettings.cost_weight, activeModelId, routingProfiles, profileWorkspaceBinding, warehouseMappings, mock, reloadProfiles]);

  // Delete a profile
  const deleteProfile = useCallback(async (id: number) => {
    if (mock) {
      setRoutingProfiles(prev => prev.filter(p => p.id !== id));
    } else {
      try {
        await api.del(`/api/routing/profiles/${id}`);
        await reloadProfiles();
      } catch {
        // Fallback: remove locally
        setRoutingProfiles(prev => prev.filter(p => p.id !== id));
      }
    }
    if (activeProfileId === id) {
      setActiveProfileId(null);
    }
  }, [activeProfileId, mock, reloadProfiles]);

  // Set a profile as the default (used by API when accessed programmatically)
  const setDefaultProfile = useCallback(async (id: number) => {
    if (mock) {
      setRoutingProfiles(prev => prev.map(p => ({
        ...p,
        is_default: p.id === id,
      })));
    } else {
      try {
        await api.put(`/api/routing/profiles/${id}/default`, {});
        await reloadProfiles();
      } catch {
        // Fallback: update locally
        setRoutingProfiles(prev => prev.map(p => ({
          ...p,
          is_default: p.id === id,
        })));
      }
    }
  }, [mock, reloadProfiles]);

  // Clear active profile (work with unsaved config)
  const clearActiveProfile = useCallback(() => {
    setActiveProfileId(null);
  }, []);

  // Derive whether current state differs from saved config
  const hasUnsavedChanges = useMemo(() => {
    if (routingMode !== savedRoutingConfig.routingMode) return true;
    if (routingMode === "single") {
      if (singleEngineId !== savedRoutingConfig.singleEngineId) return true;
    } else if (routingMode === "smart") {
      if (activeModelId !== savedRoutingConfig.activeModelId) return true;
      const currentIds = [...enabledEngineIds].sort();
      const savedIds = [...savedRoutingConfig.enabledEngineIds].sort();
      if (currentIds.length !== savedIds.length || currentIds.some((id, i) => id !== savedIds[i])) return true;
    } else if (routingMode === "benchmark") {
      // Benchmark mode doesn't use profiles/save — always considered "no unsaved changes"
      return false;
    }
    if (Math.abs(routingSettings.cost_weight - savedRoutingConfig.routingPriority) > 0.01) return true;
    // Check workspace binding (Round 16)
    const currentWs = profileWorkspaceBinding;
    const savedWs = savedRoutingConfig.workspaceBinding;
    if ((currentWs === null) !== (savedWs === null)) return true;
    if (currentWs && savedWs && currentWs.workspaceId !== savedWs.workspaceId) return true;
    // Check warehouse mappings (Round 16)
    const currentMappings = warehouseMappings.filter(m => m.warehouseId !== null);
    const savedMappings = (savedRoutingConfig.warehouseMappings ?? []).filter(m => m.warehouseId !== null);
    if (currentMappings.length !== savedMappings.length) return true;
    for (const cm of currentMappings) {
      const sm = savedMappings.find(m => m.engineId === cm.engineId);
      if (!sm || sm.warehouseId !== cm.warehouseId) return true;
    }
    return false;
  }, [routingMode, singleEngineId, enabledEngineIds, routingSettings.cost_weight, activeModelId, savedRoutingConfig, profileWorkspaceBinding, warehouseMappings]);

  const saveRoutingConfig = useCallback(async () => {
    // When a profile is loaded, update it in place
    await saveProfile();
  }, [saveProfile]);

  const rollbackRoutingConfig = useCallback(() => {
    // Restore routing mode
    setRoutingMode(savedRoutingConfig.routingMode);
    // Restore single engine
    setSingleEngineId(savedRoutingConfig.singleEngineId);
    // Restore engines
    setEnabledEngineIds(new Set(savedRoutingConfig.enabledEngineIds));
    // Restore routing priority
    setRoutingSettings(prev => ({
      ...prev,
      cost_weight: savedRoutingConfig.routingPriority,
      fit_weight: 1 - savedRoutingConfig.routingPriority,
    }));
    // Restore active model
    setActiveModelId(savedRoutingConfig.activeModelId);
    // Restore workspace binding and warehouse mappings (Round 16)
    setProfileWorkspaceBinding(savedRoutingConfig.workspaceBinding ?? null);
    setWarehouseMappings(savedRoutingConfig.warehouseMappings ?? []);
  }, [savedRoutingConfig]);

  // Benchmark definitions (Phase 15 — Engine Setup view)
  const [benchmarkDefinitions, setBenchmarkDefinitions] = useState<BenchmarkDefinition[]>(
    mock ? MOCK_BENCHMARK_DEFINITIONS : []
  );
  const reloadBenchmarkDefinitions = useCallback(async () => {
    if (mock) {
      setBenchmarkDefinitions(MOCK_BENCHMARK_DEFINITIONS);
      return;
    }
    try {
      const defs = await api.get<BenchmarkDefinition[]>("/api/benchmarks");
      setBenchmarkDefinitions(defs);
    } catch {
      // API error — keep current state
    }
  }, [mock]);

  // createModel — declared here because it depends on benchmarkDefinitions (state ordering matters in React)
  const createModel = useCallback(async (linkedEngines: string[], trainingCollectionIds: number[]): Promise<Model> => {
    if (mock) {
      const newId = Math.max(0, ...models.map(m => m.id)) + 1;
      const relevantDefs = benchmarkDefinitions.filter(d =>
        trainingCollectionIds.includes(d.collection_id) && linkedEngines.includes(d.engine_id)
      );
      const totalRuns = relevantDefs.reduce((sum, d) => sum + d.run_count, 0);
      const newModel: Model = {
        id: newId,
        linked_engines: linkedEngines,
        latency_model: {
          r_squared: +(0.8 + Math.random() * 0.15).toFixed(2),
          mae_ms: +(8 + Math.random() * 15).toFixed(1),
          model_path: `/models/latency_v${newId}.joblib`,
        },
        is_active: false,
        created_at: new Date().toISOString(),
        benchmark_count: relevantDefs.length,
        training_queries: totalRuns * 10,
        training_collection_ids: trainingCollectionIds,
      };
      setModels(prev => [...prev, newModel]);
      return newModel;
    }
    // Real mode: POST /api/models/train with collection_ids
    const newModel = await api.post<Model>("/api/models/train", {
      collection_ids: trainingCollectionIds,
    });
    // Refresh the full models list from the server
    await reloadModels();
    return newModel;
  }, [mock, models, benchmarkDefinitions, reloadModels]);

  // Re-load engines when workspace connection changes (backend returns both DuckDB + Databricks)
  useEffect(() => {
    reloadEngines();
  }, [connectedWorkspace]); // eslint-disable-line react-hooks/exhaustive-deps

  // Helper: apply a profile's config to all working state (used at startup and by loadProfile)
  const applyProfileConfig = useCallback((profile: RoutingProfile) => {
    setActiveProfileId(profile.id);
    setSavedRoutingConfig({ ...profile.config });
    setRoutingModeRaw(profile.config.routingMode);
    setSingleEngineId(profile.config.singleEngineId);
    setActiveModelId(profile.config.activeModelId);
    setEnabledEngineIds(new Set(profile.config.enabledEngineIds));
    setRoutingSettings(prev => ({
      ...prev,
      cost_weight: profile.config.routingPriority,
      fit_weight: 1 - profile.config.routingPriority,
    }));
    setProfileWorkspaceBinding(profile.config.workspaceBinding ?? null);
    setWarehouseMappings(profile.config.warehouseMappings ?? []);
  }, []);

  // Initial data load
  useEffect(() => {
    if (mock) {
      // In mock mode, data is already initialized from MOCK_* constants
      return;
    }
    // Startup sequence: fetch settings + profiles, then hydrate default profile
    const initProfiles = async () => {
      try {
        // 1. Fetch routing settings (includes active_profile_id)
        const settingsResp = await api.get<RoutingSettingsResponse>("/api/routing/settings");
        setRoutingSettings({
          fit_weight: settingsResp.fit_weight,
          cost_weight: settingsResp.cost_weight,
          running_bonus_duckdb: settingsResp.running_bonus_duckdb,
          running_bonus_databricks: settingsResp.running_bonus_databricks,
        });

        // 2. Fetch profiles
        const profiles = await api.get<RoutingProfile[]>("/api/routing/profiles");
        setRoutingProfiles(profiles);

        // 3. Determine which profile to load
        const targetId = settingsResp.active_profile_id;
        const targetProfile = targetId != null
          ? profiles.find(p => p.id === targetId)
          : undefined;
        const defaultProfile = profiles.find(p => p.is_default);
        const profileToLoad = targetProfile ?? defaultProfile;

        // 4. Apply profile config to working state
        if (profileToLoad) {
          applyProfileConfig(profileToLoad);
        }
      } catch {
        // Backend unreachable — defaults remain (single mode, empty state)
      }
    };

    initProfiles();
    reloadWorkspaces().then(() => {
      // Load warehouses after workspaces — needs connected workspace
      reloadWarehouses();
    });
    reloadModels();
    reloadStorageProbes();
    reloadBenchmarkDefinitions();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AppContext.Provider value={{
      editorSql, setEditorSql, queryResult, setQueryResult,
      collectionContext, setCollectionContext,
      refreshCollections, triggerRefreshCollections,
      activeCollectionId, setActiveCollectionId,
      workspaces, setWorkspaces, connectedWorkspace, reloadWorkspaces,
      warehouses, selectedWarehouseId, warehousesLoading, reloadWarehouses, selectWarehouse, clearWarehouses,
      engines, reloadEngines, enabledEngineIds, toggleEngineEnabled, setAllEnginesEnabled,
      singleEngineId: derivedSingleEngineId, setSingleEngineId,
      scaleEngine, scalingEngineIds,
      routingMode, setRoutingMode,
      benchmarkEngineIds, toggleBenchmarkEngine, setBenchmarkEngines,
      runMode,
      panelMode, setPanelMode,
      activeModelId, setActiveModelId, models, reloadModels, deleteModel, activateModel, deactivateModel, createModel,
      routingSettings, updateRoutingSettings,
      storageProbes, reloadStorageProbes, runStorageProbes, probesRunning,
      benchmarkDefinitions, reloadBenchmarkDefinitions,
      leftPanelTab, setLeftPanelTab,
      savedRoutingConfig, hasUnsavedChanges, saveRoutingConfig, rollbackRoutingConfig,
      routingProfiles, activeProfileId, activeProfileName,
      loadProfile, saveProfile, saveProfileAs, deleteProfile, setDefaultProfile, clearActiveProfile,
      profileWorkspaceBinding, unlinkProfileWorkspace,
      warehouseMappings, setWarehouseMapping,
      discoveredWarehouses, reloadDiscoveredWarehouses,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
