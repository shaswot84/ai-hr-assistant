/**
 * Module-level store for the current JWT access token.
 *
 * The plain fetch wrapper in `lib/api.ts` reads this token from here and adds
 * it as `Authorization: Bearer <token>` on every request, so React components
 * never need to touch the token directly. Set on login, cleared on logout.
 */
const STORAGE_KEY = "auth_token";

let currentToken: string | null = null;

/** Returns the stored JWT access token, or null if signed out. */
export function getAuthToken(): string | null {
  return currentToken;
}

/** Stores the JWT access token and persists it for reloads (called on login). */
export function setAuthToken(token: string | null): void {
  currentToken = token;
  try {
    if (token) window.localStorage.setItem(STORAGE_KEY, token);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failures (e.g. privacy mode)
  }
}

/** Restores a persisted token (e.g. on page reload), then stores it in memory. */
export function initAuthToken(): string | null {
  if (currentToken) return currentToken;
  let token: string | null = null;
  try {
    token = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    token = null;
  }
  if (token) {
    currentToken = token;
    return token;
  }
  return null;
}

/** Clears the stored token (sign-out). */
export function clearAuthToken(): void {
  setAuthToken(null);
}