import React, { useState, useEffect } from "react";
import { mockApi } from "@/mocks/api";
import type { RoutingRule } from "@/types";
import { ChevronRight, ChevronDown, Shield, Info } from "lucide-react";
import { RoutingInfoModal } from "./RoutingInfoModal";

/** Readable labels for system rule condition types. */
const CONDITION_LABELS: Record<string, string> = {
  table_type: "Table type",
  has_governance: "Governance",
  data_source_format: "Format",
};

export const SystemRules: React.FC = () => {
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [showInfoModal, setShowInfoModal] = useState(false);

  useEffect(() => {
    mockApi.getRoutingRules().then((all) => {
      setRules(all.filter((r) => r.is_system));
    });
  }, []);

  return (
    <>
      <div className="text-[12px]">
        <div className="w-full px-3 py-1.5 border-b border-panel-border flex items-center gap-1.5 hover:bg-muted/50">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 flex-1 min-w-0"
          >
            {expanded ? (
              <ChevronDown size={12} className="text-muted-foreground shrink-0" />
            ) : (
              <ChevronRight size={12} className="text-muted-foreground shrink-0" />
            )}
            <Shield size={12} className="text-primary shrink-0" />
            <span className="font-semibold text-foreground">System Rules</span>
            <span className="text-[10px] text-muted-foreground">({rules.length})</span>
          </button>
          <button
            onClick={() => setShowInfoModal(true)}
            className="text-muted-foreground hover:text-primary transition-colors shrink-0"
            title="How System Rules work"
          >
            <Info size={12} />
          </button>
        </div>

        {expanded && (
          <div className="px-3 py-2">
            {rules.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No system rules loaded.</p>
            ) : (
              <div className="space-y-1">
                {rules.map((r) => {
                  const condLabel = CONDITION_LABELS[r.condition_type] ?? r.condition_type;
                  const target = r.target_engine === "databricks" ? "Databricks" : "DuckDB";
                  return (
                    <div
                      key={r.id}
                      className="text-[11px] text-muted-foreground truncate"
                    >
                      {condLabel} = <span className="text-foreground font-medium">{r.condition_value}</span>{" "}
                      &rarr; {target}
                    </div>
                  );
                })}
              </div>
            )}
            <p className="mt-2 text-[10px] text-muted-foreground italic">
              System rules are built-in and cannot be edited.
            </p>
          </div>
        )}
      </div>

      <RoutingInfoModal
        open={showInfoModal}
        onClose={() => setShowInfoModal(false)}
        stage="system"
      />
    </>
  );
};
