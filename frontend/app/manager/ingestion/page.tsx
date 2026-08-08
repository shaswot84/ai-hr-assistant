"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ListSkeleton } from "@/components/loading";
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

export default function ManagerIngestionPage() {
  const { addToast } = useToast();
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [category, setCategory] = useState("POLICY");
  const [docType, setDocType] = useState("policy");
  const [description, setDescription] = useState("");
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
      form.append("document_type", docType);
      if (description) form.append("description", description);

      try {
        const uploaded = await api.upload(form);
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
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Document Ingestion</h1>
        <p className="mt-0.5 text-sm text-gray-500">
          Upload HR documents — the worker parses, chunks, embeds and indexes them so they become
          searchable in the Knowledge Service.
        </p>
      </div>

      {notice && (
        <div
          className={`rounded-xl border p-4 text-sm ${
            notice.kind === "ok"
              ? "border-green-200 bg-green-50 text-green-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="card p-6">
          <h2 className="mb-4 text-lg font-bold text-gray-900">Upload document</h2>
          <form onSubmit={handleUpload} className="space-y-4">
            <div>
              <label className="label" htmlFor="file">
                File (pdf, docx, md, …) — multiple files allowed
              </label>
              <input
                id="file"
                type="file"
                multiple
                accept=".md,.pdf,.docx,.doc,.txt,.pptx,.xlsx,text/markdown,application/pdf"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                className="block w-full cursor-pointer rounded-lg border border-gray-300 bg-white text-sm text-gray-700 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-blue-700"
              />
              {files.length > 0 && (
                <p className="mt-1.5 text-xs text-gray-500">
                  {files.length} file{files.length === 1 ? "" : "s"} selected:{" "}
                  {files.map((f) => f.name).join(", ")}
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                <label className="label" htmlFor="docType">
                  Document type
                </label>
                <input
                  id="docType"
                  type="text"
                  className="input"
                  value={docType}
                  placeholder="e.g. policy, procedure, form"
                  onChange={(e) => setDocType(e.target.value)}
                />
              </div>
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

            <div className="flex items-center gap-3">
              <button className="btn-primary" type="submit" disabled={uploading}>
                {uploading ? "Uploading…" : "Upload & index"}
              </button>
              {busyJobs.length > 0 && (
                <span className="badge bg-amber-100 text-amber-700">indexing in progress…</span>
              )}
            </div>
          </form>
        </section>

        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-100 px-6 py-4">
            <h2 className="text-lg font-bold text-gray-900">Document registry</h2>
            {documents.length > 0 && (
              <button type="button" onClick={handleClearAll} className="btn-danger-ghost">
                Clear all
              </button>
            )}
          </div>

          {loading ? (
            <ListSkeleton rows={5} />
          ) : documents.length === 0 ? (
            <p className="px-6 py-12 text-center text-sm text-gray-400">
              No documents yet — upload one to get started.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-sky-100 bg-sky-50">
                  <tr>
                    <th className="table-th">Title</th>
                    <th className="table-th">Category</th>
                    <th className="table-th">Status</th>
                    <th className="table-th">Versions</th>
                    <th className="table-th">Chunks</th>
                    <th className="table-th">Updated</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {documents.map((d) => (
                    <tr
                      key={d.document_id}
                      className="cursor-pointer transition-colors hover:bg-sky-50"
                      onClick={() => {
                        setSelectedId(d.document_id);
                        loadDetail(d.document_id);
                      }}
                    >
                      <td className="table-td font-medium text-gray-900">
                        {d.title}
                        {d.document_id === selectedId && (
                          <span className="ml-1 text-xs text-blue-600">✓</span>
                        )}
                      </td>
                      <td className="table-td">{d.category}</td>
                      <td className="table-td">
                        <span className={`badge ${statusBadgeClass(d.status)}`}>{d.status}</span>
                      </td>
                      <td className="table-td">{d.versions}</td>
                      <td className="table-td">{d.current_chunks}</td>
                      <td className="table-td text-xs text-gray-500">{fmtDate(d.updated_at)}</td>
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
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-6 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-gray-900">{detail.title}</h2>
              <span className="badge bg-blue-50 text-blue-700">{detail.category}</span>
              <span className={`badge ${statusBadgeClass(detail.status)}`}>{detail.status}</span>
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

          <div className="divide-y divide-gray-100">
            {detail.versions.map((v) => (
              <div key={v.document_version_id} className="px-6 py-4">
                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                  <span className="font-medium text-gray-700">
                    v{v.version_number}
                    {v.is_current ? " (current)" : ""}
                  </span>
                  <span>· {fmtDate(v.uploaded_at)}</span>
                  <span>· {v.original_filename}</span>
                  <code className="rounded bg-gray-100 px-1.5 py-0.5">{v.checksum.slice(0, 12)}</code>
                </div>

                {v.change_summary && (
                  <p className="mb-3 text-xs text-gray-500">
                    change summary: <code>{v.change_summary}</code>
                  </p>
                )}

                {v.ingestion_jobs.length === 0 ? (
                  <p className="text-sm text-gray-400">No ingestion job for this version.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead className="border-b border-sky-100 bg-sky-50">
                        <tr>
                          <th className="table-th">Job</th>
                          <th className="table-th">Status</th>
                          <th className="table-th">Failure</th>
                          <th className="table-th">Parser / Chunker / Embedder</th>
                          <th className="table-th">Completed</th>
                          <th className="table-th" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {v.ingestion_jobs.map((j) => (
                          <tr key={j.ingestion_job_id}>
                            <td className="table-td">
                              <code>{shortId(j.ingestion_job_id)}</code>
                            </td>
                            <td className="table-td">
                              <span className={`badge ${statusBadgeClass(j.status)}`}>{j.status}</span>
                            </td>
                            <td className="table-td text-xs text-gray-500">
                              {j.failure_reason || "—"}
                              {j.error_message && <div>{j.error_message}</div>}
                            </td>
                            <td className="table-td text-xs text-gray-500">
                              {[j.parser_version, j.chunking_strategy, j.embedding_model]
                                .filter(Boolean)
                                .join(" · ") || "—"}
                            </td>
                            <td className="table-td text-xs text-gray-500">{fmtDate(j.completed_at)}</td>
                            <td className="table-td">
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
