// =============================================================================
// Mock Mode — enabled via ?mock=true URL parameter
// =============================================================================
// When active:
//   - Auth is bypassed (auto-authenticated as "admin")
//   - API calls return mock data instead of hitting the backend
//   - Enables rapid frontend iteration without minikube/backend running
// =============================================================================

/** Check if mock mode is enabled via URL param */
export function isMockMode(): boolean {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  return params.get("mock") === "true";
}
