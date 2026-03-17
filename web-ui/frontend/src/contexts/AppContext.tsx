import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { RoutingMode, QueryExecutionResult } from "../types";

interface AuthContextType {
  token: string | null;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({ token: null, login: () => {}, logout: () => {} });

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem("auth_token"));

  const login = useCallback((t: string) => {
    sessionStorage.setItem("auth_token", t);
    setToken(t);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem("auth_token");
    setToken(null);
  }, []);

  return <AuthContext.Provider value={{ token, login, logout }}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);

// App State
interface AppContextType {
  routingMode: RoutingMode;
  setRoutingMode: (m: RoutingMode) => void;
  editorSql: string;
  setEditorSql: (s: string) => void;
  queryResult: QueryExecutionResult | null;
  setQueryResult: (r: QueryExecutionResult | null) => void;
  isDatabricksConfigured: boolean;
  setDatabricksConfigured: (b: boolean) => void;
  settingsOpen: boolean;
  setSettingsOpen: (b: boolean) => void;
  // Collection context for editor
  collectionContext: { collectionName: string; queryLabel: string; originalSql: string } | null;
  setCollectionContext: (c: { collectionName: string; queryLabel: string; originalSql: string } | null) => void;
  refreshCollections: number;
  triggerRefreshCollections: () => void;
}

const AppContext = createContext<AppContextType>(null!);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [routingMode, setRoutingMode] = useState<RoutingMode>("smart");
  const [editorSql, setEditorSql] = useState("");
  const [queryResult, setQueryResult] = useState<QueryExecutionResult | null>(null);
  const [isDatabricksConfigured, setDatabricksConfigured] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [collectionContext, setCollectionContext] = useState<{ collectionName: string; queryLabel: string; originalSql: string } | null>(null);
  const [refreshCollections, setRefresh] = useState(0);

  const triggerRefreshCollections = useCallback(() => setRefresh(p => p + 1), []);

  return (
    <AppContext.Provider value={{
      routingMode, setRoutingMode, editorSql, setEditorSql,
      queryResult, setQueryResult, isDatabricksConfigured, setDatabricksConfigured,
      settingsOpen, setSettingsOpen, collectionContext, setCollectionContext,
      refreshCollections, triggerRefreshCollections,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
