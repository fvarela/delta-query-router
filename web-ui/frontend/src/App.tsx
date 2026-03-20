import { AppProvider } from "./contexts/AppContext";
import { TopBar } from "./components/TopBar/TopBar";
import { WorkspaceManager } from "./components/RightPanel/WorkspaceManager";
import { CatalogBrowser } from "./components/LeftPanel/CatalogBrowser";
import { CenterPanel } from "./components/CenterPanel/CenterPanel";
import { RightPanel } from "./components/RightPanel/RightPanel";

const App = () => (
  <AppProvider>
    <div className="h-screen flex flex-col overflow-hidden min-w-[1280px]">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        {/* Left Panel - 20% — Workspaces + Catalogs stacked */}
        <div className="w-[20%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <WorkspaceManager />
          <div className="border-t border-panel-border" />
          <CatalogBrowser />
        </div>
        {/* Center Panel - 50% — Query editor + results */}
        <div className="w-[50%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
          <CenterPanel />
        </div>
        {/* Right Panel - 30% — Workspaces, Engines, Routing config */}
        <div className="w-[30%] bg-background overflow-hidden flex flex-col">
          <RightPanel />
        </div>
      </div>
    </div>
  </AppProvider>
);

export default App;
