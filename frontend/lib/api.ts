import type { Application, ApplicationDetail, Vacancy } from "@/lib/types";

/** Base URL of the FastAPI backend. Overridable at build time via NEXT_PUBLIC_API_BASE_URL. */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/**
 * Error thrown when the backend responds with a non-2xx status.
 * Carries the HTTP status code and the `detail` message from the API body.
 */
export class ApiError extends Error {
  status: number;
  detail: string;

  /**
   * @param status HTTP status code returned by the API.
   * @param detail Human-readable error detail from the API response body.
   */
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Turns a non-OK fetch Response into an ApiError, extracting the `detail`
 * field from the JSON body when present. Always throws (never returns).
 *
 * @param res The fetch Response to parse.
 * @returns A rejected promise carrying an ApiError.
 */
async function parseError(res: Response): Promise<never> {
  let detail = `Request failed with status ${res.status}`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (body?.detail) detail = JSON.stringify(body.detail);
  } catch {
    // non-JSON body; keep default message
  }
  throw new ApiError(res.status, detail);
}

/**
 * Shared fetch helper: sends the request to the API base URL with cookies
 * (credentials: "include") and a JSON content type unless the body is a
 * FormData (e.g. file uploads). Throws an ApiError for non-2xx responses.
 *
 * @template T The expected response body type.
 * @param path API path appended to API_BASE_URL (e.g. "/api/vacancies").
 * @param init Optional fetch options (method, body, headers, ...).
 * @returns The parsed JSON response body as type T.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) await parseError(res);
  return (await res.json()) as T;
}

/**
 * Client for the FastAPI backend. Each method maps to one REST endpoint and
 * wraps the response via `request` (JSON, cookies included).
 */
export const api = {
  /** GET /api/auth/me — returns the current authenticated user's context. */
  me: () => request<{ user: import("@/lib/types").UserContext }>("/api/auth/me"),

  /**
   * POST /api/auth/dev-login — dev-only stub login that simulates a user with
   * the given coarse role. Used by the login page in place of Keycloak.
   */
  devLogin: (role: string, email?: string, name?: string) =>
    request<{ user: import("@/lib/types").UserContext }>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ role, email, name }),
    }),

  /** POST /api/auth/logout — ends the current session. */
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  /** GET /api/vacancies — lists all vacancies (any role). */
  listVacancies: () => request<Vacancy[]>("/api/vacancies"),

  /** GET /api/vacancies/{id} — fetches a single vacancy. */
  getVacancy: (id: string) => request<Vacancy>(`/api/vacancies/${id}`),

  /** POST /api/vacancies — creates a new vacancy (manager only). */
  createVacancy: (body: {
    title: string;
    department_name: string;
    description?: string | null;
    employment_type: string;
    opening_date?: string | null;
    closing_date?: string | null;
  }) =>
    request<Vacancy>("/api/vacancies", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** GET /api/vacancies/{id}/applications — lists applications for a vacancy (manager only). */
  vacancyApplications: (vacancyId: string) =>
    request<ApplicationDetail[]>(`/api/vacancies/${vacancyId}/applications`),

  /** GET /api/applications/{id} — fetches one application with detail (manager only). */
  applicationDetail: (applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/${applicationId}`),

  /** GET /api/applications/mine — lists the current candidate's applications. */
  myApplications: () => request<Application[]>("/api/applications/mine"),

  /** GET /api/applications/mine/{id} — fetches one of the current candidate's applications. */
  myApplication: (applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/mine/${applicationId}`),

  /**
   * POST /api/vacancies/{id}/applications — submits an application for a
   * vacancy by uploading a resume file as multipart FormData.
   */
  apply: (vacancyId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Application>(`/api/vacancies/${vacancyId}/applications`, {
      method: "POST",
      body: formData,
    });
  },

  /** POST /api/applications/{id}/decision — approves (shortlists) or rejects an application (manager only). */
  decide: (applicationId: string, action: "approve" | "reject") =>
    request<Application>(`/api/applications/${applicationId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  /** URL of the candidate's uploaded resume, opened in a new tab to download. */
  resumeUrl: (applicationId: string) => `${API_BASE_URL}/api/applications/${applicationId}/resume`,
};
