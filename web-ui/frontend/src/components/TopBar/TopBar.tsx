import React from "react";
import { useAuth } from "@/contexts/AuthContext";

export const TopBar: React.FC = () => {
  const { username, logout } = useAuth();

  return (
    <div className="h-10 border-b border-panel-border bg-background flex items-center px-4 shrink-0">
      <span className="text-[13px] font-semibold text-foreground">Delta Router</span>
      <div className="ml-auto flex items-center gap-3">
        {username && (
          <span className="text-[12px] text-muted-foreground">{username}</span>
        )}
        <button
          onClick={logout}
          className="text-[12px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  );
};
