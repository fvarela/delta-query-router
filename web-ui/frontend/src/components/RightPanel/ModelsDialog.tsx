import React, { useState, useMemo } from "react";
import { useApp } from "@/contexts/AppContext";
import { X, Plus, Trash2, CheckCircle2, Circle, Brain, ChevronRight, ChevronLeft, HardDrive, Cloud, AlertTriangle, Database, BarChart3 } from "lucide-react";
import type { Model, BenchmarkDefinition, EngineCatalogEntry } from "@/types";

interface ModelsDialogProps {
  open: boolean;
  onClose: () => void;
}

type WizardStep = 1 | 2 | 3;
type DialogView = { kind: "list" } | { kind: "wizard" } | { kind: "detail"; modelId: number };

// ---- Collection eligibility for training ----
interface CollectionTrainingInfo {
  collectionId: number;
  collectionName: string;
  /** For each selected engine, how many runs exist for this collection */
  runsByEngine: { engineId: string; engineName: string; runCount: number }[];
  /** Whether ALL selected engines have >= 1 run */
  eligible: boolean;
  /** min(runCount) across selected engines — the effective run count */
  effectiveRuns: number;
}

export const ModelsDialog: React.FC<ModelsDialogProps> = ({ open, onClose }) => {
  const [view, setView] = useState<DialogView>({ kind: "list" });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-background border border-panel-border rounded-lg shadow-lg w-[580px] max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {view.kind === "wizard" ? (
          <NewModelWizard onBack={() => setView({ kind: "list" })} onClose={onClose} />
        ) : view.kind === "detail" ? (
          <ModelDetailView modelId={view.modelId} onBack={() => setView({ kind: "list" })} onClose={onClose} />
        ) : (
          <ModelListView
            onNewModel={() => setView({ kind: "wizard" })}
            onViewDetail={(id) => setView({ kind: "detail", modelId: id })}
            onClose={onClose}
          />
        )}
      </div>
    </div>
  );
};

// ---- Model List View ----
const ModelListView: React.FC<{
  onNewModel: () => void;
  onViewDetail: (id: number) => void;
  onClose: () => void;
}> = ({ onNewModel, onViewDetail, onClose }) => {
  const { models, activeModelId, activateModel, deactivateModel, deleteModel, engines } = useApp();
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const getEngineNames = (engineIds: string[]) =>
    engineIds.map(id => engines.find(e => e.id === id)?.display_name ?? id);

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-panel-border">
        <div className="flex items-center gap-2">
          <Brain size={14} className="text-primary" />
          <span className="font-semibold text-sm text-foreground">ML Models</span>
          <span className="text-xs text-muted-foreground">({models.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onNewModel}
            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors"
          >
            <Plus size={11} />
            New Model
          </button>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Model list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {models.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            No models yet. Create one by selecting engines and training data.
          </div>
        ) : (
          <div className="divide-y divide-panel-border">
            {models.map(model => (
              <ModelRow
                key={model.id}
                model={model}
                isActive={model.id === activeModelId}
                engineNames={getEngineNames(model.linked_engines)}
                onClick={() => onViewDetail(model.id)}
                onActivate={() => activateModel(model.id)}
                onDeactivate={() => deactivateModel(model.id)}
                confirmDelete={confirmDeleteId === model.id}
                onDeleteRequest={() => setConfirmDeleteId(model.id)}
                onDeleteConfirm={() => { deleteModel(model.id); setConfirmDeleteId(null); }}
                onDeleteCancel={() => setConfirmDeleteId(null)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
};

// ---- Single Model Row ----
const ModelRow: React.FC<{
  model: Model;
  isActive: boolean;
  engineNames: string[];
  onClick: () => void;
  onActivate: () => void;
  onDeactivate: () => void;
  confirmDelete: boolean;
  onDeleteRequest: () => void;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
}> = ({ model, isActive, engineNames, onClick, onActivate, onDeactivate, confirmDelete, onDeleteRequest, onDeleteConfirm, onDeleteCancel }) => {
  return (
    <div
      className={`px-4 py-3 cursor-pointer ${isActive ? "bg-primary/5" : "hover:bg-muted/30"} transition-colors`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: model info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[12px] font-semibold text-foreground">Model #{model.id}</span>
            {isActive && (
              <span className="flex items-center gap-0.5 px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-[9px] font-medium rounded-full">
                <CheckCircle2 size={8} />
                Active
              </span>
            )}
            <ChevronRight size={10} className="text-muted-foreground/40 ml-auto" />
          </div>
          {/* Metrics */}
          <div className="flex items-center gap-3 mb-1.5">
            <span className="text-[11px] text-muted-foreground">
              R<sup>2</sup>={model.latency_model.r_squared}
            </span>
            {model.latency_model.mae_ms != null && (
              <span className="text-[11px] text-muted-foreground">
                MAE={model.latency_model.mae_ms}ms
              </span>
            )}
            {model.training_queries != null && (
              <span className="text-[11px] text-muted-foreground">
                {model.training_queries} training queries
              </span>
            )}
          </div>
          {/* Engines */}
          <div className="flex flex-wrap gap-1">
            {engineNames.map((name, i) => (
              <span key={i} className="px-1.5 py-0.5 bg-muted/60 text-[10px] text-muted-foreground rounded">
                {name}
              </span>
            ))}
          </div>
          {/* Created date */}
          <div className="mt-1 text-[10px] text-muted-foreground/60">
            Created {new Date(model.created_at).toLocaleDateString()}
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-1.5 shrink-0 pt-0.5" onClick={e => e.stopPropagation()}>
          {isActive ? (
            <button
              onClick={onDeactivate}
              className="px-2 py-1 text-[10px] font-medium text-muted-foreground border border-border rounded hover:bg-muted/50 transition-colors"
              title="Deactivate model"
            >
              Deactivate
            </button>
          ) : (
            <button
              onClick={onActivate}
              className="px-2 py-1 text-[10px] font-medium text-primary border border-primary/30 rounded hover:bg-primary/10 transition-colors"
              title="Activate model"
            >
              Activate
            </button>
          )}
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <button
                onClick={onDeleteConfirm}
                className="px-1.5 py-1 text-[10px] font-medium text-red-600 hover:text-red-700 transition-colors"
              >
                Confirm
              </button>
              <button
                onClick={onDeleteCancel}
                className="px-1.5 py-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={onDeleteRequest}
              className="p-1 text-muted-foreground hover:text-red-500 transition-colors"
              title="Delete model"
            >
              <Trash2 size={12} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ---- Model Detail View ----
const ModelDetailView: React.FC<{
  modelId: number;
  onBack: () => void;
  onClose: () => void;
}> = ({ modelId, onBack, onClose }) => {
  const { models, engines, benchmarkDefinitions, activeModelId, activateModel, deactivateModel } = useApp();

  const model = models.find(m => m.id === modelId);
  if (!model) {
    return (
      <>
        <div className="flex items-center justify-between px-4 py-3 border-b border-panel-border">
          <div className="flex items-center gap-2">
            <button onClick={onBack} className="text-muted-foreground hover:text-foreground transition-colors">
              <ChevronLeft size={16} />
            </button>
            <span className="font-semibold text-sm text-foreground">Model not found</span>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          This model no longer exists.
        </div>
      </>
    );
  }

  const isActive = model.id === activeModelId;
  const linkedEngines = engines.filter(e => model.linked_engines.includes(e.id));
  const trainingCollectionIds = model.training_collection_ids ?? [];

  // Build training collection details: for each collection, show per-engine run counts
  const trainingDetails = useMemo(() => {
    if (trainingCollectionIds.length === 0) return [];

    return trainingCollectionIds.map(collectionId => {
      // Find the collection name from benchmark definitions
      const defForCollection = benchmarkDefinitions.find(d => d.collection_id === collectionId);
      const collectionName = defForCollection?.collection_name ?? `Collection #${collectionId}`;

      // For each linked engine, find how many runs exist
      const engineRuns = model.linked_engines.map(engineId => {
        const def = benchmarkDefinitions.find(
          d => d.collection_id === collectionId && d.engine_id === engineId
        );
        const engineEntry = engines.find(e => e.id === engineId);
        return {
          engineId,
          engineName: engineEntry?.display_name ?? engineId,
          engineType: engineEntry?.engine_type ?? "duckdb",
          runCount: def?.run_count ?? 0,
        };
      });

      const totalRuns = engineRuns.reduce((sum, er) => sum + er.runCount, 0);

      return { collectionId, collectionName, engineRuns, totalRuns };
    });
  }, [trainingCollectionIds, benchmarkDefinitions, model.linked_engines, engines]);

  const totalTrainingRuns = trainingDetails.reduce((sum, td) => sum + td.totalRuns, 0);

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-panel-border">
        <div className="flex items-center gap-2">
          <button onClick={onBack} className="text-muted-foreground hover:text-foreground transition-colors">
            <ChevronLeft size={16} />
          </button>
          <Brain size={14} className="text-primary" />
          <span className="font-semibold text-sm text-foreground">Model #{model.id}</span>
          {isActive && (
            <span className="flex items-center gap-0.5 px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-[9px] font-medium rounded-full">
              <CheckCircle2 size={8} />
              Active
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isActive ? (
            <button
              onClick={() => deactivateModel(model.id)}
              className="px-2 py-1 text-[10px] font-medium text-muted-foreground border border-border rounded hover:bg-muted/50 transition-colors"
            >
              Deactivate
            </button>
          ) : (
            <button
              onClick={() => activateModel(model.id)}
              className="px-2 py-1 text-[10px] font-medium text-primary border border-primary/30 rounded hover:bg-primary/10 transition-colors"
            >
              Activate
            </button>
          )}
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0 px-4 py-3 space-y-4">
        {/* Metrics */}
        <div>
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Performance Metrics</span>
          <div className="mt-1.5 grid grid-cols-3 gap-2">
            <div className="px-3 py-2 bg-muted/30 rounded border border-border text-center">
              <div className="text-[16px] font-semibold text-foreground">{model.latency_model.r_squared}</div>
              <div className="text-[10px] text-muted-foreground">R² Score</div>
            </div>
            {model.latency_model.mae_ms != null && (
              <div className="px-3 py-2 bg-muted/30 rounded border border-border text-center">
                <div className="text-[16px] font-semibold text-foreground">{model.latency_model.mae_ms}<span className="text-[11px] font-normal text-muted-foreground">ms</span></div>
                <div className="text-[10px] text-muted-foreground">MAE</div>
              </div>
            )}
            {model.training_queries != null && (
              <div className="px-3 py-2 bg-muted/30 rounded border border-border text-center">
                <div className="text-[16px] font-semibold text-foreground">{model.training_queries}</div>
                <div className="text-[10px] text-muted-foreground">Training Queries</div>
              </div>
            )}
          </div>
        </div>

        {/* Linked Engines */}
        <div>
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
            Linked Engines ({linkedEngines.length})
          </span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {linkedEngines.map(e => (
              <span key={e.id} className="flex items-center gap-1 px-2 py-1 bg-muted/60 text-[11px] text-foreground rounded border border-border">
                {e.engine_type === "duckdb" ? <HardDrive size={9} className="text-emerald-600" /> : <Cloud size={9} className="text-blue-600" />}
                {e.display_name}
              </span>
            ))}
          </div>
        </div>

        {/* Training Data */}
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Training Data ({trainingDetails.length} collection{trainingDetails.length !== 1 ? "s" : ""})
            </span>
            {totalTrainingRuns > 0 && (
              <span className="text-[10px] text-muted-foreground">
                {totalTrainingRuns} total runs
              </span>
            )}
          </div>
          {trainingDetails.length === 0 ? (
            <div className="mt-1.5 px-3 py-2 bg-muted/20 rounded border border-border text-[11px] text-muted-foreground/70">
              No training collection data recorded for this model.
            </div>
          ) : (
            <div className="mt-1.5 space-y-2">
              {trainingDetails.map(td => (
                <div key={td.collectionId} className="px-3 py-2.5 bg-muted/30 rounded border border-border">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Database size={10} className="text-primary/70" />
                    <span className="text-[11px] font-medium text-foreground">{td.collectionName}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">
                      {td.totalRuns} run{td.totalRuns !== 1 ? "s" : ""} total
                    </span>
                  </div>
                  {/* Per-engine run counts — mini table */}
                  <div className="space-y-0.5">
                    {td.engineRuns.map(er => (
                      <div key={er.engineId} className="flex items-center gap-2 ml-1">
                        {er.engineType === "duckdb" ? (
                          <HardDrive size={8} className="text-emerald-600/70 shrink-0" />
                        ) : (
                          <Cloud size={8} className="text-blue-600/70 shrink-0" />
                        )}
                        <span className="text-[10px] text-muted-foreground flex-1">{er.engineName}</span>
                        <div className="flex items-center gap-1.5">
                          {/* Mini bar visualization */}
                          <div className="w-16 h-1.5 bg-border rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${er.runCount > 0 ? "bg-primary/60" : "bg-transparent"}`}
                              style={{ width: `${Math.min(er.runCount / 3 * 100, 100)}%` }}
                            />
                          </div>
                          <span className={`text-[10px] tabular-nums w-8 text-right ${er.runCount === 0 ? "text-muted-foreground/40" : "text-foreground"}`}>
                            {er.runCount} run{er.runCount !== 1 ? "s" : ""}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Metadata footer */}
        <div className="text-[10px] text-muted-foreground/60 pt-1 border-t border-border space-y-0.5">
          <div>Created: {new Date(model.created_at).toLocaleString()}</div>
          {model.updated_at && (
            <div>Updated: {new Date(model.updated_at).toLocaleString()}</div>
          )}
          <div>Model path: {model.latency_model.model_path}</div>
        </div>
      </div>
    </>
  );
};

// ---- New Model Wizard ----
const NewModelWizard: React.FC<{
  onBack: () => void;
  onClose: () => void;
}> = ({ onBack, onClose }) => {
  const { engines, benchmarkDefinitions, createModel, activateModel } = useApp();
  const [step, setStep] = useState<WizardStep>(1);
  const [selectedEngines, setSelectedEngines] = useState<Set<string>>(new Set());
  const [selectedCollections, setSelectedCollections] = useState<Set<number>>(new Set());

  // Step 1: All engines that have at least one benchmark definition
  const enginesWithBenchmarks = useMemo(() => {
    const engineIdsWithDefs = new Set(benchmarkDefinitions.map(d => d.engine_id));
    return engines.filter(e => engineIdsWithDefs.has(e.id));
  }, [engines, benchmarkDefinitions]);

  // Step 2: Collections eligible for training (all selected engines have >= 1 run)
  const collectionInfos = useMemo((): CollectionTrainingInfo[] => {
    if (selectedEngines.size === 0) return [];

    // Group definitions by collection
    const collectionMap = new Map<number, { name: string; defs: BenchmarkDefinition[] }>();
    for (const def of benchmarkDefinitions) {
      if (!collectionMap.has(def.collection_id)) {
        collectionMap.set(def.collection_id, { name: def.collection_name, defs: [] });
      }
      collectionMap.get(def.collection_id)!.defs.push(def);
    }

    const result: CollectionTrainingInfo[] = [];
    for (const [collectionId, { name, defs }] of collectionMap) {
      const runsByEngine: CollectionTrainingInfo["runsByEngine"] = [];
      let eligible = true;
      let minRuns = Infinity;

      for (const engineId of selectedEngines) {
        const def = defs.find(d => d.engine_id === engineId);
        const engineName = engines.find(e => e.id === engineId)?.display_name ?? engineId;
        const runCount = def?.run_count ?? 0;
        runsByEngine.push({ engineId, engineName, runCount });
        if (runCount === 0) eligible = false;
        if (runCount > 0) minRuns = Math.min(minRuns, runCount);
      }

      result.push({
        collectionId,
        collectionName: name,
        runsByEngine,
        eligible,
        effectiveRuns: eligible ? minRuns : 0,
      });
    }

    // Sort: eligible first, then by name
    return result.sort((a, b) => {
      if (a.eligible !== b.eligible) return a.eligible ? -1 : 1;
      return a.collectionName.localeCompare(b.collectionName);
    });
  }, [selectedEngines, benchmarkDefinitions, engines]);

  const eligibleCollections = collectionInfos.filter(c => c.eligible);

  const toggleEngine = (id: string) => {
    setSelectedEngines(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    // Clear collection selection when engines change (eligibility changes)
    setSelectedCollections(new Set());
  };

  const toggleCollection = (id: number) => {
    setSelectedCollections(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const canProceedStep1 = selectedEngines.size >= 2;
  const canProceedStep2 = selectedCollections.size >= 1;

  const handleCreate = () => {
    const model = createModel([...selectedEngines], [...selectedCollections]);
    activateModel(model.id);
    onBack(); // Return to model list
  };

  // Total effective training runs
  const totalEffectiveRuns = useMemo(() => {
    return collectionInfos
      .filter(c => selectedCollections.has(c.collectionId))
      .reduce((sum, c) => sum + c.effectiveRuns, 0);
  }, [collectionInfos, selectedCollections]);

  const stepTitles: Record<WizardStep, string> = {
    1: "Select Engines",
    2: "Select Training Data",
    3: "Review & Create",
  };

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-panel-border">
        <div className="flex items-center gap-2">
          <button onClick={onBack} className="text-muted-foreground hover:text-foreground transition-colors">
            <ChevronLeft size={16} />
          </button>
          <Brain size={14} className="text-primary" />
          <span className="font-semibold text-sm text-foreground">New Model</span>
          <span className="text-xs text-muted-foreground">Step {step}/3 — {stepTitles[step]}</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Step indicator */}
      <div className="px-4 py-2 border-b border-panel-border bg-muted/20">
        <div className="flex items-center gap-1">
          {([1, 2, 3] as WizardStep[]).map(s => (
            <React.Fragment key={s}>
              <div className={`flex items-center gap-1 ${s === step ? "text-primary" : s < step ? "text-emerald-600" : "text-muted-foreground/40"}`}>
                <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border ${
                  s === step ? "border-primary bg-primary text-primary-foreground" :
                  s < step ? "border-emerald-500 bg-emerald-100 text-emerald-700" :
                  "border-border bg-background text-muted-foreground/40"
                }`}>
                  {s < step ? <CheckCircle2 size={10} /> : s}
                </div>
                <span className="text-[10px] font-medium hidden sm:inline">{stepTitles[s]}</span>
              </div>
              {s < 3 && <div className={`flex-1 h-px mx-1 ${s < step ? "bg-emerald-400" : "bg-border"}`} />}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Step content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {step === 1 && (
          <Step1Engines
            engines={enginesWithBenchmarks}
            allEngines={engines}
            selectedEngines={selectedEngines}
            toggleEngine={toggleEngine}
            benchmarkDefinitions={benchmarkDefinitions}
          />
        )}
        {step === 2 && (
          <Step2Collections
            collectionInfos={collectionInfos}
            selectedCollections={selectedCollections}
            toggleCollection={toggleCollection}
          />
        )}
        {step === 3 && (
          <Step3Review
            selectedEngines={selectedEngines}
            selectedCollections={selectedCollections}
            engines={engines}
            collectionInfos={collectionInfos}
            totalEffectiveRuns={totalEffectiveRuns}
          />
        )}
      </div>

      {/* Footer navigation */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-panel-border">
        <button
          onClick={() => step > 1 ? setStep((step - 1) as WizardStep) : onBack()}
          className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground border border-border rounded transition-colors"
        >
          <ChevronLeft size={12} />
          {step === 1 ? "Cancel" : "Back"}
        </button>
        {step < 3 ? (
          <button
            onClick={() => setStep((step + 1) as WizardStep)}
            disabled={step === 1 ? !canProceedStep1 : !canProceedStep2}
            className="flex items-center gap-1 px-3 py-1.5 text-[11px] font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next
            <ChevronRight size={12} />
          </button>
        ) : (
          <button
            onClick={handleCreate}
            className="flex items-center gap-1 px-4 py-1.5 text-[11px] font-medium bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors"
          >
            <Plus size={11} />
            Create Model
          </button>
        )}
      </div>
    </>
  );
};

// ---- Step 1: Select Engines ----
const Step1Engines: React.FC<{
  engines: EngineCatalogEntry[];
  allEngines: EngineCatalogEntry[];
  selectedEngines: Set<string>;
  toggleEngine: (id: string) => void;
  benchmarkDefinitions: BenchmarkDefinition[];
}> = ({ engines, allEngines, selectedEngines, toggleEngine, benchmarkDefinitions }) => {
  const duckdbEngines = engines.filter(e => e.engine_type === "duckdb");
  const databricksEngines = engines.filter(e => e.engine_type === "databricks_sql");

  const getDefCount = (engineId: string) =>
    benchmarkDefinitions.filter(d => d.engine_id === engineId).length;

  const getTotalRuns = (engineId: string) =>
    benchmarkDefinitions.filter(d => d.engine_id === engineId).reduce((sum, d) => sum + d.run_count, 0);

  // Also show engines with NO benchmarks (greyed out)
  const enginesWithoutBenchmarks = allEngines.filter(e => !engines.some(eb => eb.id === e.id));

  return (
    <div className="px-4 py-3 space-y-3">
      <p className="text-[11px] text-muted-foreground">
        Select the engines this model will route queries between. At least 2 engines required.
        Only engines with benchmark runs are available.
      </p>

      {/* DuckDB */}
      {duckdbEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <HardDrive size={10} className="text-emerald-600" />
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">DuckDB</span>
          </div>
          <div className="space-y-0.5">
            {duckdbEngines.map(e => (
              <label
                key={e.id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors hover:bg-muted/50 ${
                  selectedEngines.has(e.id) ? "bg-primary/5" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedEngines.has(e.id)}
                  onChange={() => toggleEngine(e.id)}
                  className="accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground">{e.display_name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {getDefCount(e.id)} collections, {getTotalRuns(e.id)} runs
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Databricks */}
      {databricksEngines.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5">
            <Cloud size={10} className="text-blue-600" />
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Databricks SQL</span>
          </div>
          <div className="space-y-0.5">
            {databricksEngines.map(e => (
              <label
                key={e.id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors hover:bg-muted/50 ${
                  selectedEngines.has(e.id) ? "bg-primary/5" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedEngines.has(e.id)}
                  onChange={() => toggleEngine(e.id)}
                  className="accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground">{e.display_name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {getDefCount(e.id)} collections, {getTotalRuns(e.id)} runs
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Engines without benchmarks (informational) */}
      {enginesWithoutBenchmarks.length > 0 && (
        <div className="pt-1 border-t border-border">
          <span className="text-[10px] text-muted-foreground/60">
            {enginesWithoutBenchmarks.length} engine{enginesWithoutBenchmarks.length !== 1 ? "s" : ""} without benchmark data:{" "}
            {enginesWithoutBenchmarks.map(e => e.display_name).join(", ")}
          </span>
        </div>
      )}

      {selectedEngines.size > 0 && selectedEngines.size < 2 && (
        <div className="flex items-center gap-1.5 text-[10px] text-amber-600">
          <AlertTriangle size={10} />
          Select at least 2 engines for the model to route between.
        </div>
      )}
    </div>
  );
};

// ---- Step 2: Select Training Data (Collections) ----
const Step2Collections: React.FC<{
  collectionInfos: CollectionTrainingInfo[];
  selectedCollections: Set<number>;
  toggleCollection: (id: number) => void;
}> = ({ collectionInfos, selectedCollections, toggleCollection }) => {
  const eligible = collectionInfos.filter(c => c.eligible);
  const ineligible = collectionInfos.filter(c => !c.eligible);

  return (
    <div className="px-4 py-3 space-y-3">
      <p className="text-[11px] text-muted-foreground">
        Select collections to use as training data. Only collections where <span className="font-medium">all</span> selected
        engines have at least 1 benchmark run are eligible.
      </p>

      {eligible.length === 0 ? (
        <div className="py-4 text-center text-[11px] text-amber-600">
          <AlertTriangle size={14} className="mx-auto mb-1" />
          No collections have benchmark runs for all selected engines. Go back and adjust engine selection.
        </div>
      ) : (
        <div className="space-y-1">
          {eligible.map(info => (
            <label
              key={info.collectionId}
              className={`block px-3 py-2 rounded border cursor-pointer transition-colors ${
                selectedCollections.has(info.collectionId)
                  ? "border-primary/30 bg-primary/5"
                  : "border-transparent hover:bg-muted/50"
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedCollections.has(info.collectionId)}
                  onChange={() => toggleCollection(info.collectionId)}
                  className="accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground">{info.collectionName}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  {info.effectiveRuns} run{info.effectiveRuns !== 1 ? "s" : ""} per engine
                </span>
              </div>
              {/* Per-engine breakdown */}
              <div className="ml-6 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                {info.runsByEngine.map(re => (
                  <span key={re.engineId} className="text-[10px] text-muted-foreground">
                    {re.engineName}: {re.runCount} run{re.runCount !== 1 ? "s" : ""}
                    {re.runCount > info.effectiveRuns && (
                      <span className="text-muted-foreground/50"> (using latest {info.effectiveRuns})</span>
                    )}
                  </span>
                ))}
              </div>
            </label>
          ))}
        </div>
      )}

      {/* Ineligible collections (dimmed) */}
      {ineligible.length > 0 && (
        <div className="pt-2 border-t border-border space-y-1">
          <span className="text-[10px] font-medium text-muted-foreground/60 uppercase tracking-wider">
            Ineligible ({ineligible.length})
          </span>
          {ineligible.map(info => (
            <div key={info.collectionId} className="px-3 py-1.5 opacity-50">
              <div className="flex items-center gap-2">
                <input type="checkbox" disabled className="accent-primary" />
                <span className="text-[11px] text-muted-foreground">{info.collectionName}</span>
              </div>
              <div className="ml-6 mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5">
                {info.runsByEngine.map(re => (
                  <span
                    key={re.engineId}
                    className={`text-[10px] ${re.runCount === 0 ? "text-red-400 font-medium" : "text-muted-foreground"}`}
                  >
                    {re.engineName}: {re.runCount === 0 ? "no runs" : `${re.runCount} run${re.runCount !== 1 ? "s" : ""}`}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ---- Step 3: Review & Confirm ----
const Step3Review: React.FC<{
  selectedEngines: Set<string>;
  selectedCollections: Set<number>;
  engines: EngineCatalogEntry[];
  collectionInfos: CollectionTrainingInfo[];
  totalEffectiveRuns: number;
}> = ({ selectedEngines, selectedCollections, engines, collectionInfos, totalEffectiveRuns }) => {
  const selectedEngineList = engines.filter(e => selectedEngines.has(e.id));
  const selectedCollectionInfos = collectionInfos.filter(c => selectedCollections.has(c.collectionId));

  // Estimate: 10 queries per run (mock data uses 10-query collections by default)
  const estimatedTrainingQueries = totalEffectiveRuns * selectedEngines.size * 10;

  return (
    <div className="px-4 py-3 space-y-4">
      <p className="text-[11px] text-muted-foreground">
        Review your selections below. The model will be trained on the latest runs for each collection.
      </p>

      {/* Engines */}
      <div>
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
          Engines ({selectedEngineList.length})
        </span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {selectedEngineList.map(e => (
            <span key={e.id} className="flex items-center gap-1 px-2 py-1 bg-muted/60 text-[11px] text-foreground rounded border border-border">
              {e.engine_type === "duckdb" ? <HardDrive size={9} className="text-emerald-600" /> : <Cloud size={9} className="text-blue-600" />}
              {e.display_name}
            </span>
          ))}
        </div>
      </div>

      {/* Collections */}
      <div>
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
          Training Data ({selectedCollectionInfos.length} collection{selectedCollectionInfos.length !== 1 ? "s" : ""})
        </span>
        <div className="mt-1.5 space-y-1.5">
          {selectedCollectionInfos.map(info => (
            <div key={info.collectionId} className="px-3 py-2 bg-muted/30 rounded border border-border">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-foreground">{info.collectionName}</span>
                <span className="text-[10px] text-muted-foreground">
                  {info.effectiveRuns} run{info.effectiveRuns !== 1 ? "s" : ""} per engine
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3">
                {info.runsByEngine.map(re => (
                  <span key={re.engineId} className="text-[10px] text-muted-foreground">
                    {re.engineName}: {re.runCount} available
                    {re.runCount > info.effectiveRuns && ` (using ${info.effectiveRuns})`}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary */}
      <div className="px-3 py-2 bg-primary/5 rounded border border-primary/20">
        <span className="text-[10px] font-medium text-primary uppercase tracking-wider">Training Summary</span>
        <div className="mt-1 text-[11px] text-foreground space-y-0.5">
          <div>{selectedEngineList.length} engines x {totalEffectiveRuns} effective runs x {selectedCollectionInfos.length} collection{selectedCollectionInfos.length !== 1 ? "s" : ""}</div>
          <div className="text-muted-foreground">~{estimatedTrainingQueries} estimated training data points</div>
        </div>
      </div>
    </div>
  );
};
