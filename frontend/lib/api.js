const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  } catch {
    throw new Error(`Cannot reach the backend at ${BASE}${path} — is the docker stack running?`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else detail = JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  listDocuments: () => request("/api/knowledge/documents"),
  getDocument: (id) => request(`/api/knowledge/documents/${id}`),
  upload: (formData) => request("/api/knowledge/documents/upload", { method: "POST", body: formData }),
  deleteDocument: (id) => request(`/api/knowledge/documents/${id}`, { method: "DELETE" }),
  clearDocuments: () => request("/api/knowledge/documents", { method: "DELETE" }),
  getJob: (id) => request(`/api/knowledge/jobs/${id}`),
  retryJob: (id) => request(`/api/knowledge/jobs/${id}/retry`, { method: "POST" }),
  search: (params) => request(`/api/knowledge/search?${new URLSearchParams(params)}`),
};

export async function pollJob(jobId, { intervalMs = 2000, timeoutMs = 180000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await api.getJob(jobId);
    if (job.status === "INDEXED" || job.status === "FAILED") return job;
    if (Date.now() > deadline) throw new Error("Timed out waiting for the ingestion job");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
