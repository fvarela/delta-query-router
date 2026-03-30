import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { api, setAuthToken, clearAuthToken, hasAuthToken, AUTH_UNAUTHORIZED_EVENT } from "@/lib/api";
import type { LoginResponse } from "../types";

interface AuthContextType {
  isAuthenticated: boolean;
  username: string | null;
  isLoggingIn: boolean;
  loginError: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>(null!);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(() => hasAuthToken());
  const [username, setUsername] = useState<string | null>(() => {
    return sessionStorage.getItem("auth_username");
  });
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  // Listen for 401 events from the API client
  useEffect(() => {
    const handler = () => {
      setIsAuthenticated(false);
      setUsername(null);
      sessionStorage.removeItem("auth_username");
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handler);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handler);
  }, []);

  const login = useCallback(async (user: string, password: string) => {
    setIsLoggingIn(true);
    setLoginError(null);
    try {
      const resp = await api.post<LoginResponse>("/api/auth/login", { username: user, password });
      setAuthToken(resp.token);
      sessionStorage.setItem("auth_username", user);
      setUsername(user);
      setIsAuthenticated(true);
    } catch (err: any) {
      const message = err instanceof Error && err.message !== "Unauthorized"
        ? err.message
        : "Login failed";
      setLoginError(message);
      throw err;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearAuthToken();
    sessionStorage.removeItem("auth_username");
    setIsAuthenticated(false);
    setUsername(null);
    setLoginError(null);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, username, isLoggingIn, loginError, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
