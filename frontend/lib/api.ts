import type {
  Application,
  ApplicationDetail,
  ApplicationStatusView,
  UserContext,
  Vacancy,
} from "@/lib/types";
import { getAuthToken } from "@/lib/auth";

/** Base URL of the FastAPI backend. Overridable at build time via NEXT_PUBLIC_API_BASE_URL. */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** Error thrown when the backend responds with a non-2xx status. */
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

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
 * Shared fetch helper: attaches the current JWT (Authorization: Bearer) and
 * a JSON content type unless the body is FormData (file uploads). Throws an
 * ApiError for non-2xx responses.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE_URL}${path}`, { headers, ...init });
  if (!res.ok) await parseError(res);
  return (await res.json()) as T;
}

export const api = {
  me: () => request<{ user: UserContext }>("/api/auth/me"),

  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string; user: UserContext }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) }
    ),

  listVacancies: () => request<Vacancy[]>("/api/vacancies"),

  getVacancy: (id: string) => request<Vacancy>(`/api/vacancies/${id}`),

  closeVacancy: (id: string) =>
    request<Vacancy>(`/api/vacancies/${id}/close`, { method: "POST" }),

  reopenVacancy: (id: string) =>
    request<Vacancy>(`/api/vacancies/${id}/reopen`, { method: "POST" }),

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

  allApplications: () => request<ApplicationDetail[]>("/api/applications"),

  vacancyApplications: (vacancyId: string) =>
    request<ApplicationDetail[]>(`/api/vacancies/${vacancyId}/applications`),

  applicationDetail: (applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/${applicationId}`),

  myApplications: () => request<ApplicationStatusView[]>("/api/applications/mine"),

  myApplication: (applicationId: string) =>
    request<ApplicationStatusView>(`/api/applications/mine/${applicationId}`),

  apply: (vacancyId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<ApplicationStatusView>(`/api/vacancies/${vacancyId}/applications`, {
      method: "POST",
      body: formData,
    });
  },

  decide: (applicationId: string, action: "approve" | "reject") =>
    request<Application>(`/api/applications/${applicationId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  /** URL of the candidate's uploaded resume; opened directly (the browser sends the stored token via a query-less GET, so this is used inside an authenticated fetch/download, not a plain <a href>). */
  resumeUrl: (applicationId: string) =>
    `${API_BASE_URL}/api/applications/${applicationId}/resume`,

  getResumeReviewPrompt: () =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/resume-review-prompt"
    ),

  setResumeReviewPrompt: (prompt: string) =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/resume-review-prompt",
      { method: "PUT", body: JSON.stringify({ prompt }) }
    ),

  resetResumeReviewPrompt: () =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/resume-review-prompt/reset",
      { method: "POST" }
    ),
};

/** Pulls the filename out of a `Content-Disposition: attachment; filename="..."` header. */
function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) return null;
  const match = /filename="?([^";]+)"?/.exec(header);
  return match ? match[1] : null;
}

/**
 * Fetch the resume as a Blob (authenticated) and trigger a browser download.
 *
 * The server knows the resume's real extension (PDF vs DOCX) from the
 * stored object key; `filenameHint` is only a fallback for the rare case
 * the response is missing its Content-Disposition header, so it must not
 * assume any particular extension.
 */
export async function downloadResume(applicationId: string, filenameHint: string) {
  const token = getAuthToken();
  const res = await fetch(api.resumeUrl(applicationId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) await parseError(res);
  const blob = await res.blob();
  const filename = filenameFromContentDisposition(res.headers.get("Content-Disposition")) ?? filenameHint;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
