import React from "react";
import { Loader2 } from "lucide-react";

export const LoadingSpinner: React.FC<{ size?: number }> = ({ size = 16 }) => (
  <Loader2 className="animate-spin text-muted-foreground" style={{ width: size, height: size }} />
);
