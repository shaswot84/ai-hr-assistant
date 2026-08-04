import type { Application, ApplicationDetail, Vacancy } from "@/lib/types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) await parseError(res);
  return (await res.json()) as T;
}

export const api = {
  me: () => request<{ user: import("@/lib/types").UserContext }>("/api/auth/me"),

  devLogin: (role: string, email?: string, name?: string) =>
    request<{ user: import("@/lib/types").UserContext }>("/api/auth/dev-login", {
      method: "POST",
      body: JSON.stringify({ role, email, name }),
    }),

  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  listVacancies: () => request<Vacancy[]>("/api/vacancies"),

  getVacancy: (id: string) => request<Vacancy>(`/api/vacancies/${id}`),

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

  vacancyApplications: (vacancyId: string) =>
    request<ApplicationDetail[]>(`/api/vacancies/${vacancyId}/applications`),

  applicationDetail: (applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/${applicationId}`),

  myApplications: () => request<Application[]>("/api/applications/mine"),

  myApplication: (applicationId: string) =>
    request<ApplicationDetail>(`/api/applications/mine/${applicationId}`),

  apply: (vacancyId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<Application>(`/api/vacancies/${vacancyId}/applications`, {
      method: "POST",
      body: formData,
    });
  },

  decide: (applicationId: string, action: "approve" | "reject") =>
    request<Application>(`/api/applications/${applicationId}/decision`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  resumeUrl: (applicationId: string) => `${API_BASE_URL}/api/applications/${applicationId}/resume`,
};
