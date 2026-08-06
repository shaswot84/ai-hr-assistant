/**
 * JWT access token storage.
 *
 * Reads and writes `localStorage` directly on every call — there is no
 * separate in-memory cache to rehydrate on load. A prior version kept the
 * token in a module-level variable with a `initAuthToken()` function meant
 * to rehydrate it from `localStorage` on startup; nothing ever called that
 * function, so a plain page refresh reset the in-memory value to null and
 * silently logged the user out even though a valid token was still sitting
 * in storage. Reading storage directly removes the "forgot to call init"
 * failure mode entirely.
 */
const STORAGE_KEY = "auth_token";

/** Returns the stored JWT access token, or null if signed out / storage is unavailable. */
export function getAuthToken(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Stores the JWT access token (called on login). */
export function setAuthToken(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // ignore storage failures (e.g. privacy mode)
  }
}

/** Clears the stored token (sign-out). */
export function clearAuthToken(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore storage failures
  }
}
