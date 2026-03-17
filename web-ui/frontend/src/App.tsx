import { AuthProvider, AppProvider } from "./contexts/AppContext";
import { TopBar } from "./components/TopBar/TopBar";
import { SettingsModal } from "./components/SettingsModal/SettingsModal";
import { CatalogBrowser } from "./components/LeftPanel/CatalogBrowser";
import { CenterPanel } from "./components/CenterPanel/CenterPanel";
import { RightPanel } from "./components/RightPanel/RightPanel";

const App = () => (
  <AuthProvider>
    <AppProvider>
      <div className="h-screen flex flex-col overflow-hidden min-w-[1280px]">
        <TopBar />
        <div className="flex flex-1 min-h-0">
          {/* Left Panel - 20% */}
          <div className="w-[20%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
            <CatalogBrowser />
          </div>
          {/* Center Panel - 50% */}
          <div className="w-[50%] border-r border-panel-border bg-background overflow-hidden flex flex-col">
            <CenterPanel />
          </div>
          {/* Right Panel - 30% */}
          <div className="w-[30%] bg-background overflow-hidden flex flex-col">
            <RightPanel />
          </div>
        </div>
      </div>
      <SettingsModal />
    </AppProvider>
  </AuthProvider>
);

export default App;
