import React, { useState } from "react";
import { useAuth } from "@/contexts/AppContext";
import { mockApi } from "@/mocks/api";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

export const LoginForm: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await mockApi.login(username, password);
      login(res.token);
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center h-full">
      <form onSubmit={handleSubmit} className="w-80 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Log In</h2>
        <div>
          <label className="block text-[12px] font-medium text-foreground mb-1">Username</label>
          <input
            type="text" value={username} onChange={e => setUsername(e.target.value)}
            className="w-full px-3 py-1.5 border border-border rounded-md text-[13px] bg-background text-foreground"
          />
        </div>
        <div>
          <label className="block text-[12px] font-medium text-foreground mb-1">Password</label>
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full px-3 py-1.5 border border-border rounded-md text-[13px] bg-background text-foreground"
          />
        </div>
        {error && <p className="text-status-error text-[12px]">{error}</p>}
        <button
          type="submit" disabled={loading}
          className="w-full py-2 bg-primary text-primary-foreground rounded-md text-[13px] font-medium flex items-center justify-center gap-2"
        >
          {loading && <LoadingSpinner size={14} />}
          Log In
        </button>
      </form>
    </div>
  );
};
