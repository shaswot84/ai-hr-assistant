"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { useToast } from "@/components/toast";
import { api, ApiError, pollJob } from "@/lib/api";
import type {
  KnowledgeDocumentDetail,
  KnowledgeDocumentSummary,
  KnowledgeUploadResult,
} from "@/lib/types";
import { fmtDate, shortId, statusBadgeClass } from "@/lib/format";

const CATEGORIES = [
  "POLICY",
  "PROCEDURE",
  "GUIDELINE",
  "FORM",
  "TEMPLATE",
  "TRAINING_MATERIAL",
  "OTHER",
];

const ACCESS_ROLE_OPTIONS: Array<{
  key: "EMPLOYEE" | "CANDIDATE" | "VISITOR";
  label: string;
  description: string;
}> = [
  { key: "EMPLOYEE", label: "Employees", description: "Current staff can retrieve this" },
  { key: "CANDIDATE", label: "Candidates", description: "Job applicants can retrieve this" },
  { key: "VISITOR", label: "Visitors", description: "General public, no login required" },
];

const ACCESS_ROLE_CHIP_STYLE: Record<string, string> = {
  HR_ADMIN: "bg-purple-50 text-purple-700",
  EMPLOYEE: "bg-blue-50 text-blue-700",
  CANDIDATE: "bg-emerald-50 text-emerald-700",
  VISITOR: "bg-amber-50 text-amber-700",
};

const ACCESS_ROLE_SHORT_LABEL: Record<string, string> = {
  HR_ADMIN: "HR Admin",
  EMPLOYEE: "Employees",
  CANDIDATE: "Candidates",
  VISITOR: "Visitors",
};

function AccessChips({ roles }: { roles: string[] }) {
  const list = roles ?? [];
  const allRoles = ["HR_ADMIN", "EMPLOYEE", "CANDIDATE", "VISITOR"];
  if (allRoles.every((r) => list.includes(r))) {
    return (
      <span
        title="Everyone can access this file"
        className="inline-flex rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] font-medium text-zinc-600"
      >
        Everyone
      </span>
    );
  }
  return (
    <span className="flex flex-wrap gap-1">
      {list.map((r) => (
        <span
          key={r}
          title={`Only ${ACCESS_ROLE_SHORT_LABEL[r] ?? r} can access this file`}
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
            ACCESS_ROLE_CHIP_STYLE[r] ?? "bg-zinc-100 text-zinc-600"
          }`}
        >
          {ACCESS_ROLE_SHORT_LABEL[r] ?? r}
        </span>
      ))}
    </span>
  );
}

export default function ManagerIngestionPage() {
  const { addToast } = useToast();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [category, setCategory] = useState("POLICY");
  const [description, setDescription] = useState("");
  const [accessRoles, setAccessRoles] = useState<string[]>(["EMPLOYEE", "CANDIDATE", "VISITOR"]);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const listing = await api.listDocuments();
      setDocuments(listing.documents);
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof ApiError ? err.detail : "Failed to load documents.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api.getDocument(id));
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof ApiError ? err.detail : "Failed to load document detail.",
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listDocuments()
      .then((listing) => {
        if (!cancelled) setDocuments(listing.documents);
      })
      .catch((err) => {
        if (!cancelled) {
          setNotice({
            kind: "err",
            text: err instanceof ApiError ? err.detail : "Failed to load documents.",
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const hasBusy = documents.some(
      (d) => d.status === "PENDING" || d.status === "PROCESSING"
    );
    if (timerRef.current) clearInterval(timerRef.current);
    if (hasBusy) {
      timerRef.current = setInterval(() => {
        refresh();
        if (selectedId) loadDetail(selectedId);
      }, 3000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [documents, selectedId, refresh, loadDetail]);

  async function handleUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (files.length === 0) {
      setNotice({ kind: "err", text: "Choose at least one file to upload." });
      return;
    }

    setUploading(true);
    setNotice(null);
    const results: Array<{ name: string; uploaded?: KnowledgeUploadResult; error?: string }> = [];
    let failed = 0;
    let lastSelected: string | null = null;

    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("category", category);
      if (description) form.append("description", description);

      try {
        const uploaded = await api.upload(form, [...accessRoles, "HR_ADMIN"]);
        if (uploaded.status === "SKIPPED_DUPLICATE") {
          setSelectedId(uploaded.document_id);
          lastSelected = uploaded.document_id;
        } else if (uploaded.ingestion_job_id) {
          const job = await pollJob(uploaded.ingestion_job_id);
          if (job.status === "INDEXED") {
            setSelectedId(uploaded.document_id);
            lastSelected = uploaded.document_id;
          }
        }
        results.push({ name: file.name, uploaded });
      } catch (err) {
        failed += 1;
        results.push({
          name: file.name,
          error: err instanceof ApiError ? err.detail : "Upload failed.",
        });
      }
    }

    setFiles([]);
    e.currentTarget.reset();

    const lines = results.map((r) => {
      if (r.error) return `${r.name} — failed: ${r.error}`;
      if (r.uploaded?.status === "SKIPPED_DUPLICATE") {
        return `${r.name} — skipped (duplicate bytes)`;
      }
      return `${r.name} — queued`;
    });
    const okCount = results.filter((r) => !r.error).length;
    const skipped = results.filter((r) => r.uploaded?.status === "SKIPPED_DUPLICATE").length;

    if (results.length === 1 && okCount === 1 && !results[0].error) {
      const only = results[0].uploaded!;
      addToast(
        only.status === "SKIPPED_DUPLICATE"
          ? `Skipped duplicate: identical bytes are already indexed (${shortId(only.document_id)}).`
          : `Upload queued — ingestion job ${shortId(only.ingestion_job_id ?? "")}.`,
        only.status === "SKIPPED_DUPLICATE" ? "info" : "success"
      );
    } else {
      addToast(
        `${results.length} file(s) · ${okCount - skipped} indexed, ${skipped} duplicate, ${failed} failed`,
        failed > 0 ? "error" : "success"
      );
    }
    setNotice({
      kind: failed > 0 ? "err" : "ok",
      text: lines.join(" · "),
    });

    if (lastSelected) await loadDetail(lastSelected);
    setUploading(false);
    await refresh();
  }

  async function handleRetry(jobId: string) {
    setRetrying(jobId);
    setNotice(null);
    try {
      await api.retryJob(jobId);
      addToast(`Job ${shortId(jobId)} reset to PENDING — worker will retry it.`, "success");
      if (selectedId) await loadDetail(selectedId);
      await refresh();
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof ApiError ? err.detail : "Failed to retry job.",
      });
    } finally {
      setRetrying(null);
    }
  }

  async function handleDelete() {
    if (!selectedId) return;
    const title = detail?.title ?? selectedId;
    if (!window.confirm(`Delete "${title}" and remove its stored file from MinIO? This cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteDocument(selectedId);
      addToast(`Deleted "${title}".`, "success");
      setSelectedId(null);
      setDetail(null);
      await refresh();
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof ApiError ? err.detail : "Failed to delete document.",
      });
    }
  }

  async function handleClearAll() {
    if (documents.length === 0) {
      setNotice({ kind: "err", text: "Nothing to clear — no documents in the registry." });
      return;
    }
    if (!window.confirm("Delete ALL documents, chunks/embeddings and MinIO files? This cannot be undone.")) {
      return;
    }
    try {
      const result = await api.clearDocuments();
      addToast(
        `Cleared ${result.deleted_documents} documents (${result.removed_objects} objects removed).`,
        "success"
      );
      setSelectedId(null);
      setDetail(null);
      await refresh();
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof ApiError ? err.detail : "Failed to clear documents.",
      });
    }
  }

  const busyJobs = detail
    ? detail.versions.flatMap((v) =>
        v.ingestion_jobs.filter((j) => j.status === "PENDING" || j.status === "PROCESSING")
      )
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Document Ingestion"
        description="Upload HR documents — the worker parses, chunks, embeds and indexes them so they become searchable in the Knowledge Service."
        meta={
          documents.length > 0 && (
            <span className="badge bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20">
              {documents.length} documents indexed
            </span>
          )
        }
      />

      {notice && (
        <div
          className={`notice ${
            notice.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="card p-5">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-zinc-900">Upload document</h2>
            <p className="text-xs text-zinc-400">PDF, DOCX, Markdown and more — multiple files allowed</p>
          </div>
          <form onSubmit={handleUpload} className="space-y-4">
            <div>
              <label className="label" htmlFor="file">
                File
              </label>
              <input
                id="file"
                type="file"
                multiple
                accept=".md,.pdf,.docx,.doc,.txt,.pptx,.xlsx,text/markdown,application/pdf"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                className="block w-full cursor-pointer rounded-md border border-dashed border-zinc-300 bg-zinc-50/50 px-3 py-6 text-sm text-zinc-600 transition-colors file:mr-3 file:rounded-md file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-[13px] file:font-medium file:text-blue-700 hover:border-zinc-400"
              />
              {files.length > 0 && (
                <div className="mt-1.5 text-xs text-zinc-500">
                  <p>
                    {files.length} file{files.length === 1 ? "" : "s"} selected:{" "}
                    {files.map((f) => f.name).join(", ")}
                  </p>
                  <p className="mt-1 flex items-center gap-1.5">
                    <span>Access:</span>
                    <AccessChips roles={[...accessRoles, "HR_ADMIN"]} />
                  </p>
                </div>
              )}
            </div>

            <div>
              <label className="label" htmlFor="category">
                Category
              </label>
              <select
                id="category"
                className="input"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="label" htmlFor="description">
                Description (optional)
              </label>
              <textarea
                id="description"
                rows={2}
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="rounded-lg border border-zinc-200 bg-zinc-50/40 p-3.5">
              <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
                <span className="label mb-0">
                  Who can access these documents in the chatbot?
                </span>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    className="btn-ghost px-2.5 py-1 text-xs"
                    onClick={() => setAccessRoles(["EMPLOYEE", "CANDIDATE", "VISITOR"])}
                  >
                    Allow everyone
                  </button>
                  <button
                    type="button"
                    className="btn-ghost px-2.5 py-1 text-xs"
                    onClick={() => setAccessRoles([])}
                  >
                    HR only
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between rounded-md border border-zinc-200 bg-white px-3 py-2 opacity-70">
                  <div className="flex items-center gap-2.5">
                    <svg className="h-4 w-4 shrink-0 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.75}
                        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                      />
                    </svg>
                    <div>
                      <p className="text-sm font-medium text-zinc-900">HR Admin</p>
                      <p className="text-xs text-zinc-400">Always has access — cannot be removed</p>
                    </div>
                  </div>
                  <span className="rounded bg-purple-50 px-1.5 py-0.5 text-[11px] font-medium text-purple-700">
                    Locked
                  </span>
                </div>
                {ACCESS_ROLE_OPTIONS.map((role) => {
                  const checked = accessRoles.includes(role.key);
                  return (
                    <label
                      key={role.key}
                      className={`flex cursor-pointer items-center justify-between rounded-md border px-3 py-2 transition-colors ${
                        checked
                          ? "border-blue-200 bg-blue-50/50"
                          : "border-zinc-200 bg-white hover:border-zinc-300"
                      }`}
                    >
                      <div className="flex items-center gap-2.5">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) =>
                            setAccessRoles((prev) =>
                              e.target.checked
                                ? [...prev, role.key]
                                : prev.filter((r) => r !== role.key)
                            )
                          }
                          className="h-4 w-4 accent-blue-600"
                        />
                        <div>
                          <p className="text-sm font-medium text-zinc-900">{role.label}</p>
                          <p className="text-xs text-zinc-400">{role.description}</p>
                        </div>
                      </div>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          ACCESS_ROLE_CHIP_STYLE[role.key]
                        }`}
                      >
                        {checked ? "Can access" : "No access"}
                      </span>
                    </label>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-zinc-400">
                {accessRoles.length === 0
                  ? "Only HR Admin will be able to retrieve these files from the chatbot."
                  : `These files will be visible to: ${accessRoles
                      .map((r) => ACCESS_ROLE_SHORT_LABEL[r] ?? r)
                      .join(", ")}, and HR Admin.`}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button className="btn-primary" type="submit" disabled={uploading}>
                {uploading ? "Uploading…" : "Upload & index"}
              </button>
              {busyJobs.length > 0 && (
                <span className="badge bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20">
                  indexing in progress…
                </span>
              )}
            </div>
          </form>
        </section>

        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3.5">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">Document registry</h2>
              <p className="text-xs text-zinc-400">Click a row to inspect its versions and jobs</p>
            </div>
            {documents.length > 0 && (
              <button type="button" onClick={handleClearAll} className="btn-danger-ghost">
                Clear all
              </button>
            )}
          </div>

          {loading ? (
            <ListSkeleton rows={5} />
          ) : documents.length === 0 ? (
            <EmptyState
              title="No documents yet"
              description="Upload one to get started — it will be parsed, chunked, embedded and indexed automatically."
            />
          ) : (
            <div className="table-scroll max-h-[540px]">
              <table className="w-full">
                <thead className="bg-zinc-50">
                  <tr>
                    <th className="table-th">Title</th>
                    <th className="table-th">Category</th>
                    <th className="table-th">Access</th>
                    <th className="table-th">Status</th>
                    <th className="table-th text-right">Versions</th>
                    <th className="table-th text-right">Chunks</th>
                    <th className="table-th">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {documents.map((d) => (
                    <tr
                      key={d.document_id}
                      className={`table-row cursor-pointer ${
                        d.document_id === selectedId ? "bg-blue-50/40" : ""
                      }`}
                      onClick={() => {
                        setSelectedId(d.document_id);
                        loadDetail(d.document_id);
                      }}
                    >
                      <td className="table-td font-medium text-zinc-900">
                        <div className="flex items-center gap-2">
                          <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={1.75}
                              d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                            />
                          </svg>
                          {d.title}
                        </div>
                      </td>
                      <td className="table-td text-zinc-500">{d.category}</td>
                      <td className="table-td">
                        <AccessChips roles={d.role_access ?? []} />
                      </td>
                      <td className="table-td">
                        <span className={`badge ${statusBadgeClass(d.status)}`}>{d.status}</span>
                      </td>
                      <td className="table-td text-right tabular-nums text-zinc-500">{d.versions}</td>
                      <td className="table-td text-right tabular-nums text-zinc-500">{d.current_chunks}</td>
                      <td className="table-td text-xs text-zinc-500">{fmtDate(d.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {detail && (
        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-zinc-900">{detail.title}</h2>
              <span className="badge bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">{detail.category}</span>
              <span className={`badge ${statusBadgeClass(detail.status)}`}>{detail.status}</span>
              <span className="flex items-center gap-1">
                <span className="text-[11px] text-zinc-400">Access</span>
                <AccessChips roles={detail.role_access ?? []} />
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" className="btn-secondary" onClick={() => loadDetail(selectedId!)}>
                Refresh
              </button>
              <button type="button" className="btn-danger-ghost" onClick={handleDelete}>
                Delete document
              </button>
            </div>
          </div>

          <div className="divide-y divide-zinc-100">
            {detail.versions.map((v) => (
              <div key={v.document_version_id} className="px-5 py-4">
                <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-500">
                  <span className="font-medium text-zinc-700">
                    v{v.version_number}
                    {v.is_current ? " (current)" : ""}
                  </span>
                  <span>·</span>
                  <span>{fmtDate(v.uploaded_at)}</span>
                  <span>·</span>
                  <span>{v.original_filename}</span>
                  <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px]">{v.checksum.slice(0, 12)}</code>
                </div>

                {v.change_summary && (
                  <p className="mb-3 text-xs text-zinc-500">
                    change summary: <code>{v.change_summary}</code>
                  </p>
                )}

                {v.ingestion_jobs.length === 0 ? (
                  <p className="text-sm text-zinc-400">No ingestion job for this version.</p>
                ) : (
                  <div className="table-scroll max-h-[420px] rounded-md border border-zinc-100">
                    <table className="w-full">
                      <thead className="bg-zinc-50">
                        <tr>
                          <th className="table-th">Job</th>
                          <th className="table-th">Status</th>
                          <th className="table-th">Failure</th>
                          <th className="table-th hidden lg:table-cell">Parser / Chunker / Embedder</th>
                          <th className="table-th">Completed</th>
                          <th className="table-th" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-100">
                        {v.ingestion_jobs.map((j) => (
                          <tr key={j.ingestion_job_id} className="table-row">
                            <td className="table-td">
                              <code className="font-mono text-xs">{shortId(j.ingestion_job_id)}</code>
                            </td>
                            <td className="table-td">
                              <span className={`badge ${statusBadgeClass(j.status)}`}>{j.status}</span>
                            </td>
                            <td className="table-td text-xs text-zinc-500">
                              {j.failure_reason || "—"}
                              {j.error_message && <div className="text-red-500">{j.error_message}</div>}
                            </td>
                            <td className="table-td hidden text-xs text-zinc-500 lg:table-cell">
                              {[j.parser_version, j.chunking_strategy, j.embedding_model]
                                .filter(Boolean)
                                .join(" · ") || "—"}
                            </td>
                            <td className="table-td text-xs text-zinc-500">{fmtDate(j.completed_at)}</td>
                            <td className="table-td text-right">
                              {j.status === "FAILED" && (
                                <button
                                  type="button"
                                  className="btn-secondary"
                                  disabled={retrying === j.ingestion_job_id}
                                  onClick={() => handleRetry(j.ingestion_job_id)}
                                >
                                  {retrying === j.ingestion_job_id ? "Retrying…" : "Retry"}
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
