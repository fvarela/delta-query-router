import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { AppProvider, useApp } from "./contexts/AppContext";
import { LoginPage } from "./components/LoginPage";
import { TopBar } from "./components/TopBar/TopBar";
import { WorkspaceManager } from "./components/RightPanel/WorkspaceManager";
import { CatalogBrowser } from "./components/LeftPanel/CatalogBrowser";
import { CollectionsPanel } from "./components/LeftPanel/CollectionsPanel";

import { CenterPanel } from "./components/CenterPanel/CenterPanel";
import { EngineSetupView } from "./components/CenterPanel/EngineSetupView";
import { RightPanel } from "./components/RightPanel/RightPanel";

const LeftPanel = () => {
  const { leftPanelTab, setLeftPanelTab } = useApp();

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <WorkspaceManager />
      <div className="border-t border-panel-border" />
      {/* Tabs */}
      <div className="flex border-b border-panel-border shrink-0">
        <button
          onClick={() => setLeftPanelTab("catalog")}
          className={`flex-1 px-3 py-1.5 text-[12px] font-medium ${leftPanelTab === "catalog" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          Catalog
        </button>
        <button
          onClick={() => setLeftPanelTab("collections")}
          className={`flex-1 px-3 py-1.5 text-[12px] font-medium ${leftPanelTab === "collections" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          Collections
        </button>
      </div>
      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {leftPanelTab === "catalog" ? <CatalogBrowser /> : <CollectionsPanel />}
      </div>
    </div>
  );
};

const CenterPanelWithTabs = () => {
  const { centerTab, setCenterTab } = useApp();

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-panel-border shrink-0 bg-card">
        <button
          onClick={() => setCenterTab("query")}
          className={`px-4 py-1.5 text-[12px] font-medium transition-colors ${
            centerTab === "query"
              ? "border-b-2 border-primary text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Query
        </button>
        <button
          onClick={() => setCenterTab("engine-setup")}
          className={`px-4 py-1.5 text-[12px] font-medium transition-colors ${
            centerTab === "engine-setup"
              ? "border-b-2 border-primary text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Benchmarks
        </button>
      </div>
      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {centerTab === "query" ? <CenterPanel /> : <EngineSetupView />}
      </div>
    </div>
  );
};

const AuthenticatedApp = () => (
  <AppProvider>
    <div className="h-screen flex flex-col overflow-hidden min-w-[1280px]">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        {/* Left Panel - 20% — Workspaces + Catalog/Collections tabs */}
        <div className="w-[20%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <LeftPanel />
        </div>
        {/* Center Panel - 50% — Query editor + results OR Engine Setup */}
        <div className="w-[50%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <CenterPanelWithTabs />
        </div>
        {/* Right Panel - 30% — Routing (always visible) */}
        <div className="w-[30%] bg-background overflow-hidden flex flex-col">
          <RightPanel />
        </div>
      </div>
    </div>
  </AppProvider>
);

const AppGate = () => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <AuthenticatedApp /> : <LoginPage />;
};

const App = () => (
  <AuthProvider>
    <AppGate />
  </AuthProvider>
);

export default App;
