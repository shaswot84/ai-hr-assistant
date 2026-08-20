import type {
  Application,
  ApplicationDetail,
  ApplicationStatusView,
  AuditFilterOptions,
  AuditLogEntry,
  AuditLogsResponse,
  CompanyHoliday,
  CompanyHolidayCreateBody,
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
  TeamMemberOutOfOffice,
  UserContext,
  Vacancy,
  WorkingDaysCalculation,
  ChatCitation,
  ChatConversation,
  ChatMessage,
  ChatResponse,
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
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as unknown as T;
  }
  return (await res.json()) as T;
}

interface PromptResult {
  prompt: string;
  is_default: boolean;
}

/** Builds the get/set/reset trio for one manager-editable LLM prompt setting
 * (`/api/settings/{path}`, `.../reset`) — every prompt in Settings (resume-
 * review system/user, resume-structuring system/user, keyword-suggestion)
 * shares this exact shape, so it's generated once per prompt instead of
 * hand-written five times. */
function promptEndpoints<Name extends string>(name: Name, path: string) {
  return {
    [`get${name}`]: () => request<PromptResult>(`/api/settings/${path}`),
    [`set${name}`]: (prompt: string) =>
      request<PromptResult>(`/api/settings/${path}`, {
        method: "PUT",
        body: JSON.stringify({ prompt }),
      }),
    [`reset${name}`]: () =>
      request<PromptResult>(`/api/settings/${path}/reset`, { method: "POST" }),
  } as {
    [K in `get${Name}`]: () => Promise<PromptResult>;
  } & {
    [K in `set${Name}`]: (prompt: string) => Promise<PromptResult>;
  } & {
    [K in `reset${Name}`]: () => Promise<PromptResult>;
  };
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

  withdrawApplication: (applicationId: string) =>
    request<ApplicationStatusView>(`/api/applications/mine/${applicationId}/withdraw`, {
      method: "POST",
    }),

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

  ...promptEndpoints("ResumeReviewPrompt", "resume-review-prompt"),
  ...promptEndpoints("ResumeReviewUserPrompt", "resume-review-user-prompt"),
  ...promptEndpoints("StructuringSystemPrompt", "resume-structuring-system-prompt"),
  ...promptEndpoints("StructuringUserPrompt", "resume-structuring-user-prompt"),
  ...promptEndpoints("KeywordSuggestionPrompt", "keyword-suggestion-prompt"),

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

  upload: (formData: FormData, accessRoles?: string[]) => {
    if (accessRoles) {
      for (const role of accessRoles) formData.append("role_access", role);
    }
    return request<KnowledgeUploadResult>("/api/knowledge/documents/upload", {
      method: "POST",
      body: formData,
    });
  },

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

  listCompanyHolidays: (year?: number) =>
    request<CompanyHoliday[]>(`/api/leave/holidays${year ? `?year=${year}` : ""}`),

  createCompanyHoliday: (body: CompanyHolidayCreateBody) =>
    request<CompanyHoliday>("/api/leave/holidays", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteCompanyHoliday: (holidayId: string) =>
    request<{ success: boolean }>(`/api/leave/holidays/${holidayId}`, {
      method: "DELETE",
    }),

  calculateWorkingDays: (body: {
    start_date: string;
    end_date: string;
    is_half_day?: boolean;
    half_day_period?: string | null;
  }) =>
    request<WorkingDaysCalculation>("/api/leave/calculate-days", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  teamOutOfOffice: (params?: {
    department_id?: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.department_id) q.set("department_id", params.department_id);
    if (params?.start_date) q.set("start_date", params.start_date);
    if (params?.end_date) q.set("end_date", params.end_date);
    const qs = q.toString();
    return request<TeamMemberOutOfOffice[]>(`/api/leave/team-out-of-office${qs ? `?${qs}` : ""}`);
  },

  // ---- chat (assistant) ----------------------------------------------

  chat: (message: string, conversationId?: string) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify(conversationId ? { conversation_id: conversationId, message } : { message }),
    }),

  publicChat: (body: { message: string; history?: { role: string; content: string }[] }) =>
    request<{
      message: string;
      citations: ChatCitation[];
      confidence: number;
      low_confidence: boolean;
      agent: string;
      confidence_applicable: boolean;
      meta?: any;
      ui_widget?: any;
    }>("/api/chat/public", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listConversations: () => request<ChatConversation[]>("/api/chat/conversations"),

  listChatMessages: (conversationId: string) =>
    request<ChatMessage[]>(`/api/chat/conversations/${conversationId}/messages`),

  deleteConversation: (conversationId: string) =>
    request<void>(`/api/chat/conversations/${conversationId}`, {
      method: "DELETE",
    }),

  // ---- audit log viewer ----------------------------------------------

  listAuditLogs: (params?: {
    page?: number;
    page_size?: number;
    action?: string;
    target_type?: string;
    actor_user_id?: string;
    target_id?: string;
    authorization_result?: string;
    search?: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.page_size) q.set("page_size", String(params.page_size));
    if (params?.action) q.set("action", params.action);
    if (params?.target_type) q.set("target_type", params.target_type);
    if (params?.actor_user_id) q.set("actor_user_id", params.actor_user_id);
    if (params?.target_id) q.set("target_id", params.target_id);
    if (params?.authorization_result) q.set("authorization_result", params.authorization_result);
    if (params?.search) q.set("search", params.search);
    if (params?.start_date) q.set("start_date", params.start_date);
    if (params?.end_date) q.set("end_date", params.end_date);
    const qs = q.toString();
    return request<AuditLogsResponse>(`/api/audit/logs${qs ? `?${qs}` : ""}`);
  },

  getAuditLog: (auditId: string) => request<AuditLogEntry>(`/api/audit/logs/${auditId}`),

  getAuditFilterOptions: () => request<AuditFilterOptions>("/api/audit/filters"),
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

/** One SSE event emitted by `POST /api/chat/stream`. */
export type ChatStreamEvent =
  | { type: "turn_started"; conversation_id: string }
  | { type: "route"; route: string }
  | {
      type: "retrieval";
      rewritten_query: string;
      grounded_context: string;
      confidence: number;
      low_confidence: boolean;
      citations: ChatCitation[];
    }
  | { type: "token"; text: string }
  | { type: "message"; text: string }
  | { type: "ui_widget"; widget: any }
  | {
      type: "done";
      conversation_id: string;
      message: string;
      citations: ChatCitation[];
      confidence: number;
      low_confidence: boolean;
      confidence_applicable: boolean;
      agent: string;
      ui_widget?: any;
    }
  | { type: "error"; detail: string };

/**
 * Stream one chat turn over SSE: `turn_started`, `route`, `retrieval`,
 * then `token` events as the answer generates (or a single `message` event
 * for stub agents / no-LLM fallbacks), ending with `done`. The chat
 * endpoints require auth, so the JWT is attached.
 */
export async function* chatStream(
  body: { conversation_id?: string; message: string },
  signal?: AbortSignal
): AsyncGenerator<ChatStreamEvent> {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) await parseError(res);
  if (!res.body) throw new Error("Streaming chat returned no response body.");

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
        yield JSON.parse(payload) as ChatStreamEvent;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}

/**
 * Stream public chat over SSE for anonymous visitors (e.g. /welcome page):
 * yields tokens incrementally, ui_widgets, citations, and done event.
 */
export async function* publicChatStream(
  body: { message: string; history?: { role: string; content: string }[] },
  signal?: AbortSignal
): AsyncGenerator<ChatStreamEvent> {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}/api/chat/public/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) await parseError(res);
  if (!res.body) throw new Error("Streaming public chat returned no response body.");

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
        yield JSON.parse(payload) as ChatStreamEvent;
      }
    }
  } finally {
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
