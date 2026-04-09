import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/contexts/AppContext";
import { ChevronDown, Star, Trash2, Cloud, Filter } from "lucide-react";

export const ProfileSelector: React.FC = () => {
  const {
    routingProfiles, activeProfileId, activeProfileName,
    loadProfile, deleteProfile, setDefaultProfile, clearActiveProfile,
    connectedWorkspace,
  } = useApp();

  const [isOpen, setIsOpen] = useState(false);
  const [filterWorkspace, setFilterWorkspace] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletedMessage, setDeletedMessage] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Group profiles: those matching connected workspace first, then unlinked, then other workspaces
  const sortedProfiles = [...routingProfiles].sort((a, b) => {
    // Default profile first
    if (a.is_default && !b.is_default) return -1;
    if (!a.is_default && b.is_default) return 1;
    // Then by workspace match: connected workspace profiles first
    const aWs = a.config.workspaceBinding;
    const bWs = b.config.workspaceBinding;
    const aMatch = aWs && connectedWorkspace && aWs.workspaceUrl === connectedWorkspace.url;
    const bMatch = bWs && connectedWorkspace && bWs.workspaceUrl === connectedWorkspace.url;
    if (aMatch && !bMatch) return -1;
    if (!aMatch && bMatch) return 1;
    // Then unlinked before other-workspace
    const aUnlinked = aWs === null;
    const bUnlinked = bWs === null;
    if (aUnlinked && !bUnlinked) return -1;
    if (!aUnlinked && bUnlinked) return 1;
    return a.name.localeCompare(b.name);
  });

  // Apply filter: show only profiles linked to the connected workspace (or unlinked)
  const visibleProfiles = filterWorkspace && connectedWorkspace
    ? sortedProfiles.filter(p => {
        const ws = p.config.workspaceBinding;
        return ws === null || ws.workspaceUrl === connectedWorkspace.url;
      })
    : sortedProfiles;

  return (
    <div className="px-3 py-2 border-b border-panel-border" ref={dropdownRef}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
          Profile
        </span>
        <div className="flex items-center gap-2">
          {connectedWorkspace && (
            <button
              onClick={() => setFilterWorkspace(!filterWorkspace)}
              className={`flex items-center gap-0.5 text-[10px] transition-colors ${
                filterWorkspace ? "text-primary font-medium" : "text-muted-foreground hover:text-foreground"
              }`}
              title={filterWorkspace ? "Show all profiles" : "Show only profiles for connected workspace"}
            >
              <Filter size={10} />
              {filterWorkspace ? "Filtered" : "Filter"}
            </button>
          )}
          {activeProfileId !== null && (
            <button
              onClick={() => clearActiveProfile()}
              className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              title="Work without a profile"
            >
              Detach
            </button>
          )}
        </div>
      </div>

      {/* Dropdown trigger */}
      <div className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="w-full flex items-center justify-between bg-card border border-border rounded px-2.5 py-1.5 text-left hover:bg-muted/50 transition-colors"
        >
          <span className={`text-[12px] truncate ${activeProfileName ? "font-medium text-foreground" : "text-muted-foreground italic"}`}>
            {activeProfileName ?? "No profile loaded"}
          </span>
          <ChevronDown size={12} className={`text-muted-foreground shrink-0 ml-1 transition-transform ${isOpen ? "rotate-180" : ""}`} />
        </button>

        {/* Dropdown menu */}
        {isOpen && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-md z-50 overflow-hidden max-h-[300px] overflow-y-auto">
            {visibleProfiles.length === 0 && (
              <div className="px-3 py-2 text-[12px] text-muted-foreground italic">
                {filterWorkspace ? "No profiles for this workspace" : "No saved profiles"}
              </div>
            )}
            {visibleProfiles.map(profile => {
              const isActive = profile.id === activeProfileId;
              const ws = profile.config.workspaceBinding;
              const wsMatch = ws && connectedWorkspace && ws.workspaceUrl === connectedWorkspace.url;
              const wsName = ws?.workspaceName;

              return (
                <div
                  key={profile.id}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 text-[12px] cursor-pointer transition-colors group ${
                    isActive ? "bg-primary/10 text-foreground" : "hover:bg-muted/50 text-foreground"
                  }`}
                  onClick={() => {
                    loadProfile(profile.id);
                    setIsOpen(false);
                    setConfirmDeleteId(null);
                  }}
                >
                  {/* Default star */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDefaultProfile(profile.id);
                    }}
                    className={`shrink-0 ${
                      profile.is_default
                        ? "text-amber-500"
                        : "text-transparent group-hover:text-muted-foreground/30 hover:!text-amber-400"
                    } transition-colors`}
                    title={profile.is_default ? "Default profile" : "Set as default"}
                  >
                    <Star size={11} fill={profile.is_default ? "currentColor" : "none"} />
                  </button>

                  {/* Profile name + workspace indicator */}
                  <div className="flex-1 min-w-0">
                    <span className="font-medium truncate block">{profile.name}</span>
                    {wsName && (
                      <span className={`flex items-center gap-0.5 text-[10px] ${
                        wsMatch ? "text-emerald-600" : "text-amber-600"
                      }`}>
                        <Cloud size={9} />
                        <span className="truncate">{wsName}</span>
                      </span>
                    )}
                  </div>

                  {/* Mode badge — full labels (UX #8) */}
                  <span className="text-[10px] text-muted-foreground px-1 py-0.5 rounded bg-muted/50 shrink-0">
                    {profile.config.routingMode === "single" ? "Single Engine" : "Smart Routing"}
                  </span>

                  {/* Delete button — with spacing (UX #9) and confirmation (UX #13) */}
                  {confirmDeleteId === profile.id ? (
                    <div className="flex items-center gap-1 ml-1 shrink-0" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => {
                          const name = profile.name;
                          deleteProfile(profile.id);
                          setConfirmDeleteId(null);
                          setDeletedMessage(`"${name}" deleted`);
                          setTimeout(() => setDeletedMessage(null), 2500);
                        }}
                        className="px-1.5 py-0.5 text-[10px] font-medium text-red-600 hover:text-red-700 transition-colors"
                      >
                        Delete
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-1 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(profile.id);
                      }}
                      className="shrink-0 ml-1 text-transparent group-hover:text-muted-foreground/50 hover:!text-destructive transition-colors"
                      title="Delete profile"
                    >
                      <Trash2 size={11} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Deletion notification (UX #14) */}
        {deletedMessage && (
          <div className="mt-1 text-[11px] text-amber-600 font-medium animate-pulse">
            {deletedMessage}
          </div>
        )}
      </div>
    </div>
  );
};
