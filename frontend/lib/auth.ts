const USER_ID_KEY = "lead_ops_user_id";
const API_KEY_KEY = "lead_ops_api_key";

export function saveCredentials(userId: string, apiKey: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(USER_ID_KEY, userId.trim());
  localStorage.setItem(API_KEY_KEY, apiKey.trim());
}

export function getUserId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(USER_ID_KEY);
}

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_KEY);
}

/** @deprecated use getApiKey — kept for gradual migration */
export function getToken(): string | null {
  return getApiKey();
}

/** @deprecated use saveCredentials */
export function saveToken(_token: string) {
  // no-op — login page uses saveCredentials
}

export function clearCredentials() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(USER_ID_KEY);
  localStorage.removeItem(API_KEY_KEY);
}

export function clearToken() {
  clearCredentials();
}

export function isLoggedIn(): boolean {
  return !!(getUserId() && getApiKey());
}
