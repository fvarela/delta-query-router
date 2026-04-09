import React, { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

export const LoginPage: React.FC = () => {
  const { login, isLoggingIn, loginError } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await login(username, password);
    } catch {
      // error state is managed by AuthContext
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-background">
      <div className="w-[340px]">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-[20px] font-semibold text-foreground">Delta Router</h1>
          <p className="text-[13px] text-muted-foreground mt-1">Sign in to continue</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-[12px] font-medium text-foreground mb-1">
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full h-8 px-2.5 text-[13px] rounded-md border border-input bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="admin"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-[12px] font-medium text-foreground mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full h-8 px-2.5 text-[13px] rounded-md border border-input bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          {loginError && (
            <p className="text-[12px] text-destructive">{loginError}</p>
          )}

          <button
            type="submit"
            disabled={isLoggingIn || !username || !password}
            className="w-full h-8 text-[13px] font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoggingIn ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
};
