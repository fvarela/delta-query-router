import React from "react";

type Variant = "success" | "error" | "warning" | "inactive" | "info";

const variantClasses: Record<Variant, string> = {
  success: "bg-status-success text-primary-foreground",
  error: "bg-status-error text-primary-foreground",
  warning: "bg-status-warning text-primary-foreground",
  inactive: "bg-status-inactive text-primary-foreground",
  info: "bg-primary text-primary-foreground",
};

export const StatusBadge: React.FC<{ variant: Variant; children: React.ReactNode }> = ({ variant, children }) => (
  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium ${variantClasses[variant]}`}>
    {children}
  </span>
);
