import React, { useRef, useEffect } from "react";
import type { RoutingLogEvent } from "@/types";
import { Terminal, ChevronDown, ChevronRight } from "lucide-react";

const levelColor: Record<string, string> = {
  info: "text-muted-foreground",
  rule: "text-status-success",
  decision: "text-primary",
  warn: "text-status-warning",
  error: "text-status-error",
};

const levelLabel: Record<string, string> = {
  info: "INFO",
  rule: "RULE",
  decision: "ROUTE",
  warn: "WARN",
  error: "ERROR",
};

const stageLabel: Record<string, string> = {
  parse: "PARSE",
  rules: "RULES",
  ml_model: "ML",
  engine: "ENGINE",
  execute: "EXEC",
  complete: "DONE",
};

interface RoutingLogProps {
  events: RoutingLogEvent[];
  open: boolean;
  onToggle: () => void;
  executing: boolean;
}

export const RoutingLog: React.FC<RoutingLogProps> = ({ events, open, onToggle, executing }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current && open) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length, open]);

  if (events.length === 0 && !executing) return null;

  return (
    <div className="border-t border-panel-border shrink-0">
      <button onClick={onToggle} className="flex items-center gap-1.5 w-full px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-muted">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Terminal size={12} className="text-primary" />
        Routing Log
        {executing && <span className="ml-1.5 text-[10px] font-normal text-primary animate-pulse">live</span>}
        {!executing && events.length > 0 && <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">({events.length} events)</span>}
      </button>
      {open && (
        <div ref={scrollRef} className="max-h-52 overflow-y-auto bg-[#1a1a2e] border-t border-border">
          <div className="p-2 font-mono text-[11px] leading-relaxed space-y-0">
            {events.map((ev, i) => (
              <div key={i} className="flex gap-2 py-px hover:bg-white/5">
                <span className="text-[#666] shrink-0 select-none">{ev.timestamp}</span>
                <span className={`shrink-0 w-[42px] text-right font-semibold ${levelColor[ev.level] || "text-muted-foreground"}`}>
                  {levelLabel[ev.level] || ev.level}
                </span>
                <span className="shrink-0 w-[48px] text-[#888]">
                  [{stageLabel[ev.stage] || ev.stage}]
                </span>
                <span className={`${ev.level === "decision" ? "text-primary font-semibold" : ev.level === "rule" ? "text-status-success" : ev.level === "warn" ? "text-status-warning" : ev.level === "error" ? "text-status-error" : "text-[#ccc]"}`}>
                  {ev.message}
                </span>
              </div>
            ))}
            {executing && (
              <div className="flex gap-2 py-px">
                <span className="text-[#666] shrink-0 select-none">{new Date().toLocaleTimeString("en-US", { hour12: false })}</span>
                <span className="text-primary animate-pulse">...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
