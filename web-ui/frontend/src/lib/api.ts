// =============================================================================
// API Client — thin fetch wrapper with Bearer token injection
// =============================================================================
//
// Usage:
//   import { api } from "@/lib/api";
//   const data = await api.get<SomeType>("/api/some-endpoint");
//   await api.post("/api/some-endpoint", { key: "value" });
//
// Auth flow:
//   - Reads token from sessionStorage("auth_token")
//   - Attaches Authorization: Bearer <token> to all requests
//   - On 401 response: clears token, fires "auth:unauthorized" event
//   - AuthContext listens for that event and shows the login page
// =============================================================================

const TOKEN_KEY = "auth_token";

/** Custom event fired on 401 — AuthContext listens for this */
export const AUTH_UNAUTHORIZED_EVENT = "auth:unauthorized";

class ApiClient {
  private getToken(): string | null {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  private headers(): HeadersInit {
    const h: HeadersInit = { "Content-Type": "application/json" };
    const token = this.getToken();
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  }

  private handleUnauthorized(): void {
    sessionStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }

  private async handleResponse<T>(resp: Response): Promise<T> {
    if (resp.status === 401) {
      this.handleUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || `HTTP ${resp.status}`);
    }
    return resp.json();
  }

  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const url = params ? `${path}?${new URLSearchParams(params)}` : path;
    const resp = await fetch(url, { headers: this.headers() });
    return this.handleResponse<T>(resp);
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(path, {
      method: "POST",
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return this.handleResponse<T>(resp);
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(path, {
      method: "PUT",
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return this.handleResponse<T>(resp);
  }

  async del(path: string): Promise<void> {
    const resp = await fetch(path, {
      method: "DELETE",
      headers: this.headers(),
    });
    if (resp.status === 401) {
      this.handleUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!resp.ok && resp.status !== 204) {
      const text = await resp.text();
      throw new Error(text || `HTTP ${resp.status}`);
    }
  }
}

export const api = new ApiClient();

/** Store token after successful login */
export function setAuthToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

/** Clear token on logout */
export function clearAuthToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

/** Check if a token exists (doesn't validate it) */
export function hasAuthToken(): boolean {
  return sessionStorage.getItem(TOKEN_KEY) !== null;
}
