import type {
  Application,
  ApplicationDetail,
  ApplicationStatusView,
  Department,
  Designation,
  Employee,
  EmployeeCreateBody,
  EmployeeUpdateBody,
  HireCandidateBody,
  KnowledgeCitation,
  KnowledgeChunk,
  KnowledgeClearResult,
  KnowledgeDeleteResult,
  KnowledgeDocumentDetail,
  KnowledgeDocumentSummary,
  KnowledgeJob,
  KnowledgeSearchResult,
  KnowledgeUploadResult,
  LeaveBalance,
  LeaveRequest,
  LeaveRequestCreateBody,
  LeaveRequestDetail,
  LeaveType,
  LeaveTypeCreateBody,
  LlmConfig,
  ScoringKeyword,
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
    scoring_keywords: ScoringKeyword[];
  }) =>
    request<Vacancy>("/api/vacancies", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Suggest scoring keywords + tiers from a job title/description — a starting
   * point for the manager to review, check/uncheck, and re-tier before posting. */
  suggestKeywords: (title: string, description: string) =>
    request<{ keywords: ScoringKeyword[] }>("/api/vacancies/keywords/suggest", {
      method: "POST",
      body: JSON.stringify({ title, description }),
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

  /** Public (no-login) apply: details + CV provision the candidate's account. */
  applyAsNewCandidate: (vacancyId: string, formData: FormData) =>
    request<ApplicationStatusView>(`/api/vacancies/${vacancyId}/apply`, {
      method: "POST",
      body: formData,
    }),

  decide: (applicationId: string, action: "approve" | "reject") =>
    request<Application>(`/api/applications/${applicationId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  /** Re-run the AI screening (e.g. after fixing a missing/invalid API key). */
  reEvaluate: (applicationId: string) =>
    request<Application>(`/api/applications/${applicationId}/re-evaluate`, {
      method: "POST",
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

  getKeywordSuggestionPrompt: () =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/keyword-suggestion-prompt"
    ),

  setKeywordSuggestionPrompt: (prompt: string) =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/keyword-suggestion-prompt",
      { method: "PUT", body: JSON.stringify({ prompt }) }
    ),

  resetKeywordSuggestionPrompt: () =>
    request<{ prompt: string; is_default: boolean }>(
      "/api/settings/keyword-suggestion-prompt/reset",
      { method: "POST" }
    ),

  getLlmConfig: () => request<LlmConfig>("/api/settings/llm-config"),

  setLlmConfig: (body: { api_base: string; model: string; api_key: string }) =>
    request<LlmConfig>("/api/settings/llm-config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  resetLlmConfig: () =>
    request<LlmConfig>("/api/settings/llm-config/reset", { method: "POST" }),

  listDocuments: () =>
    request<{ documents: KnowledgeDocumentSummary[] }>("/api/knowledge/documents"),

  getDocument: (id: string) =>
    request<KnowledgeDocumentDetail>(`/api/knowledge/documents/${id}`),

  upload: (formData: FormData) =>
    request<KnowledgeUploadResult>("/api/knowledge/documents/upload", {
      method: "POST",
      body: formData,
    }),

  getJob: (id: string) => request<KnowledgeJob>(`/api/knowledge/jobs/${id}`),

  retryJob: (id: string) =>
    request<KnowledgeJob>(`/api/knowledge/jobs/${id}/retry`, { method: "POST" }),

  deleteDocument: (id: string) =>
    request<KnowledgeDeleteResult>(`/api/knowledge/documents/${id}`, {
      method: "DELETE",
    }),

  clearDocuments: () =>
    request<KnowledgeClearResult>("/api/knowledge/documents", { method: "DELETE" }),

  search: (params: { q: string; category?: string; top_k?: number; generate?: boolean }) => {
    const query = new URLSearchParams({ q: params.q });
    if (params.category) query.set("category", params.category);
    if (params.top_k) query.set("top_k", String(params.top_k));
    if (params.generate !== undefined) query.set("generate", String(params.generate));
    return request<KnowledgeSearchResult>(`/api/knowledge/search?${query.toString()}`);
  },

  // ---- people (org directory) --------------------------------------

  listDepartments: () => request<Department[]>("/api/people/departments"),

  createDepartment: (name: string) =>
    request<Department>("/api/people/departments", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  listDesignations: (departmentId?: string) =>
    request<Designation[]>(
      `/api/people/designations${departmentId ? `?department_id=${departmentId}` : ""}`
    ),

  createDesignation: (body: { department_id: string; title: string; level?: number | null }) =>
    request<Designation>("/api/people/designations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listEmployees: (params?: { search?: string; department_id?: string; employment_status?: string }) => {
    const query = new URLSearchParams();
    if (params?.search) query.set("search", params.search);
    if (params?.department_id) query.set("department_id", params.department_id);
    if (params?.employment_status) query.set("employment_status", params.employment_status);
    const qs = query.toString();
    return request<Employee[]>(`/api/people/employees${qs ? `?${qs}` : ""}`);
  },

  createEmployee: (body: EmployeeCreateBody) =>
    request<Employee>("/api/people/employees", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateEmployee: (employeeId: string, body: EmployeeUpdateBody) =>
    request<Employee>(`/api/people/employees/${employeeId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  deactivateEmployee: (employeeId: string) =>
    request<Employee>(`/api/people/employees/${employeeId}/deactivate`, { method: "POST" }),

  hireCandidate: (applicationId: string, body: HireCandidateBody) =>
    request<Employee>(`/api/people/candidates/${applicationId}/hire`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  myProfile: () => request<Employee>("/api/people/me"),

  // ---- leave management ----------------------------------------------

  listLeaveTypes: () => request<LeaveType[]>("/api/leave/types"),

  createLeaveType: (body: LeaveTypeCreateBody) =>
    request<LeaveType>("/api/leave/types", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  myLeaveBalance: (year?: number) =>
    request<LeaveBalance[]>(`/api/leave/balance${year ? `?year=${year}` : ""}`),

  requestLeave: (body: LeaveRequestCreateBody) =>
    request<LeaveRequest>("/api/leave/requests", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  myLeaveRequests: () => request<LeaveRequest[]>("/api/leave/requests/mine"),

  myLeaveRequest: (leaveRequestId: string) =>
    request<LeaveRequest>(`/api/leave/requests/mine/${leaveRequestId}`),

  cancelLeaveRequest: (leaveRequestId: string) =>
    request<LeaveRequest>(`/api/leave/requests/mine/${leaveRequestId}/cancel`, {
      method: "POST",
    }),

  allLeaveRequests: () => request<LeaveRequestDetail[]>("/api/leave/requests"),

  leaveRequestDetail: (leaveRequestId: string) =>
    request<LeaveRequestDetail>(`/api/leave/requests/${leaveRequestId}`),

  decideLeaveRequest: (leaveRequestId: string, action: "approve" | "reject") =>
    request<LeaveRequestDetail>(`/api/leave/requests/${leaveRequestId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
};

/** One SSE event emitted by `GET /api/knowledge/search/stream`. */
export type SearchStreamEvent =
  | {
      type: "retrieval";
      grounded_context: string;
      confidence: number;
      low_confidence: boolean;
      citations: KnowledgeCitation[];
      chunks: KnowledgeChunk[];
    }
  | { type: "token"; text: string }
  | { type: "done" };

/**
 * Stream a knowledge search over SSE: a `retrieval` event (evidence,
 * citations, confidence) first, then `token` events as the LLM generates,
 * then a final `done` event. When no answer is generated (no LLM configured,
 * low confidence, or `generate: false`) only `retrieval` + `done` arrive and
 * the caller falls back to `grounded_context`.
 */
export async function* searchStream(
  params: { q: string; category?: string; top_k?: number; generate?: boolean },
  signal?: AbortSignal
): AsyncGenerator<SearchStreamEvent> {
  const query = new URLSearchParams({ q: params.q });
  if (params.category) query.set("category", params.category);
  if (params.top_k) query.set("top_k", String(params.top_k));
  if (params.generate !== undefined) query.set("generate", String(params.generate));

  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}/api/knowledge/search/stream?${query.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!res.ok) await parseError(res);
  if (!res.body) throw new Error("Streaming search returned no response body.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (payload === "[DONE]") return;
        yield JSON.parse(payload) as SearchStreamEvent;
      }
    }
  } finally {
    // Cancels the underlying fetch when the consumer aborts or stops early.
    await reader.cancel().catch(() => {});
  }
}

/** Poll an ingestion job until it reaches a terminal state (INDEXED or FAILED). */
export async function pollJob(
  jobId: string,
  { intervalMs = 2000, timeoutMs = 180000 }: { intervalMs?: number; timeoutMs?: number } = {}
): Promise<KnowledgeJob> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await api.getJob(jobId);
    if (job.status === "INDEXED" || job.status === "FAILED") return job;
    if (Date.now() > deadline) {
      throw new Error("Timed out waiting for the ingestion job.");
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

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
