import React, { useState } from "react";
import { X } from "lucide-react";
import { useAuth, useApp } from "@/contexts/AppContext";
import { LoginForm } from "./LoginForm";
import { DatabricksConnectionTab } from "./DatabricksConnectionTab";
import { WarehouseSelectionTab } from "./WarehouseSelectionTab";
import { EngineCatalogTab } from "./EngineCatalogTab";
import { EnginePreferencesTab } from "./EnginePreferencesTab";
import { RoutingRulesTab } from "./RoutingRulesTab";
import { RoutingSettingsTab } from "./RoutingSettingsTab";
import { ModelsTab } from "./ModelsTab";

const tabs = [
  { id: "databricks", label: "Databricks Connection" },
  { id: "warehouse", label: "Warehouse Selection" },
  { id: "engines", label: "Engine Catalog" },
  { id: "preferences", label: "Engine Preferences" },
  { id: "rules", label: "Routing Rules" },
  { id: "settings", label: "Routing Settings" },
  { id: "models", label: "Models" },
];

export const SettingsModal: React.FC = () => {
  const { settingsOpen, setSettingsOpen } = useApp();
  const { token, logout } = useAuth();
  const [activeTab, setActiveTab] = useState("databricks");

  if (!settingsOpen) return null;

  const renderContent = () => {
    if (!token) return <LoginForm />;
    switch (activeTab) {
      case "databricks": return <DatabricksConnectionTab />;
      case "warehouse": return <WarehouseSelectionTab />;
      case "engines": return <EngineCatalogTab />;
      case "preferences": return <EnginePreferencesTab />;
      case "rules": return <RoutingRulesTab />;
      case "settings": return <RoutingSettingsTab />;
      case "models": return <ModelsTab />;
      default: return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setSettingsOpen(false)}>
      <div className="absolute inset-0 bg-foreground/30" />
      <div
        className="relative bg-background border border-border rounded-lg shadow-lg flex flex-col"
        style={{ width: "80vw", height: "80vh" }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border">
          <div className="flex items-center gap-3">
            <h2 className="text-[14px] font-semibold text-foreground">Settings</h2>
            {token && (
              <span className="text-[11px] text-muted-foreground">
                Logged in as admin · <button onClick={logout} className="text-primary hover:underline">Log Out</button>
              </span>
            )}
          </div>
          <button onClick={() => setSettingsOpen(false)} className="text-muted-foreground hover:text-foreground">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 min-h-0">
          {token && (
            <div className="w-48 border-r border-border bg-card overflow-y-auto shrink-0">
              {tabs.map(t => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  className={`w-full text-left px-3 py-2 text-[12px] ${
                    activeTab === t.id ? "bg-primary text-primary-foreground font-medium" : "text-foreground hover:bg-muted"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
          <div className="flex-1 overflow-y-auto">
            {renderContent()}
          </div>
        </div>
      </div>
    </div>
  );
};
