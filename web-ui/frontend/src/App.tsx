import { useState } from "react";
import { AppProvider } from "./contexts/AppContext";
import { TopBar } from "./components/TopBar/TopBar";
import { WorkspaceManager } from "./components/RightPanel/WorkspaceManager";
import { CatalogBrowser } from "./components/LeftPanel/CatalogBrowser";
import { CollectionsPanel } from "./components/LeftPanel/CollectionsPanel";
import { CenterPanel } from "./components/CenterPanel/CenterPanel";
import { RightPanel } from "./components/RightPanel/RightPanel";

const LeftPanel = () => {
  const [tab, setTab] = useState<"catalog" | "collections">("catalog");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <WorkspaceManager />
      <div className="border-t border-panel-border" />
      {/* Tabs */}
      <div className="flex border-b border-panel-border shrink-0">
        <button
          onClick={() => setTab("catalog")}
          className={`flex-1 px-3 py-1.5 text-[12px] font-medium ${tab === "catalog" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          Catalog
        </button>
        <button
          onClick={() => setTab("collections")}
          className={`flex-1 px-3 py-1.5 text-[12px] font-medium ${tab === "collections" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          Collections
        </button>
      </div>
      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === "catalog" ? <CatalogBrowser /> : <CollectionsPanel />}
      </div>
    </div>
  );
};

const App = () => (
  <AppProvider>
    <div className="h-screen flex flex-col overflow-hidden min-w-[1280px]">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        {/* Left Panel - 20% — Workspaces + Catalog/Collections tabs */}
        <div className="w-[20%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <LeftPanel />
        </div>
        {/* Center Panel - 50% — Query editor + results */}
        <div className="w-[50%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <CenterPanel />
        </div>
        {/* Right Panel - 30% — Routing (always visible) */}
        <div className="w-[30%] bg-background overflow-hidden flex flex-col">
          <RightPanel />
        </div>
      </div>
    </div>
  </AppProvider>
);

export default App;
