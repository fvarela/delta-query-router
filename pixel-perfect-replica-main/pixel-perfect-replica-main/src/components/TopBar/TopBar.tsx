import React from "react";
import { Settings } from "lucide-react";
import { HealthIndicators } from "./HealthIndicators";
import { RoutingModeToggle } from "./RoutingModeToggle";
import { useApp } from "@/contexts/AppContext";

export const TopBar: React.FC = () => {
  const { setSettingsOpen } = useApp();

  return (
    <div className="h-12 border-b border-panel-border bg-background flex items-center justify-between px-4 shrink-0">
      <HealthIndicators />
      <RoutingModeToggle />
      <button
        onClick={() => setSettingsOpen(true)}
        className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-muted hover:bg-accent rounded-md"
      >
        <Settings size={14} />
        Settings
      </button>
    </div>
  );
};
