"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, pollJob } from "@/lib/api";
import { fmtDate, shortId, statusClass } from "@/lib/format";

const CATEGORIES = [
  "POLICY",
  "PROCEDURE",
  "GUIDELINE",
  "FORM",
  "TEMPLATE",
  "TRAINING_MATERIAL",
  "OTHER",
];

export default function IngestPage() {
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  const [category, setCategory] = useState("POLICY");
  const [docType, setDocType] = useState("policy");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState(null); // { kind: "ok"|"err", text }
  const [retrying, setRetrying] = useState(null);

  const timerRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const listing = await api.listDocuments();
      setDocuments(listing.documents);
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    }
  }, []);

  const loadDetail = useCallback(async (id) => {
    try {
      setDetail(await api.getDocument(id));
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    }
  }, []);

  // Initial load.
  useEffect(() => {
    refresh();
  }, [refresh]);

  // Follow-up refresh while any job is still in flight.
  useEffect(() => {
    const hasBusy = documents.some(
      (d) => d.status === "PENDING" || d.status === "PROCESSING"
    );
    clearInterval(timerRef.current);
    if (hasBusy) {
      timerRef.current = setInterval(() => {
        refresh();
        if (selectedId) loadDetail(selectedId);
      }, 3000);
    }
    return () => clearInterval(timerRef.current);
  }, [documents, selectedId, refresh, loadDetail]);

  async function handleUpload(e) {
    e.preventDefault();
    if (!file) {
      setMessage({ kind: "err", text: "Choose a file to upload." });
      return;
    }
    setUploading(true);
    setMessage(null);
    const form = new FormData();
    form.append("file", file);
    form.append("category", category);
    form.append("document_type", docType);
    if (description) form.append("description", description);
    try {
      const uploaded = await api.upload(form);
      setFile(null);
      e.target.reset();
      if (uploaded.status === "SKIPPED_DUPLICATE") {
        setMessage({
          kind: "ok",
          text: `Skipped duplicate: identical bytes are already indexed (document ${shortId(uploaded.document_id)}, checksum ${uploaded.checksum}).`,
        });
        setSelectedId(uploaded.document_id);
        await loadDetail(uploaded.document_id);
      } else {
        setMessage({
          kind: "ok",
          text: `Uploaded. Job ${shortId(uploaded.ingestion_job_id)} queued (${uploaded.status}) — waiting for the worker…`,
        });
        setSelectedId(uploaded.document_id);
        const job = await pollJob(uploaded.ingestion_job_id);
        setMessage(
          job.status === "INDEXED"
            ? {
                kind: "ok",
                text: `Ingestion ${job.status} — ${job.embedding_model} @ ${job.pipeline_version}.`,
              }
            : {
                kind: "err",
                text: `Ingestion ${job.status} (${job.failure_reason || "?"}): ${job.error_message || ""}`,
              }
        );
      }
    } catch (e) {
      setMessage({ kind: "err", text: `Upload failed: ${e.message}` });
    } finally {
      setUploading(false);
      await refresh();
    }
  }

  async function handleRetry(jobId) {
    setRetrying(jobId);
    setMessage(null);
    try {
      await api.retryJob(jobId);
      setMessage({ kind: "ok", text: `Job ${shortId(jobId)} reset to PENDING — worker will retry it.` });
      await loadDetail(selectedId);
      await refresh();
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    } finally {
      setRetrying(null);
    }
  }

  async function handleDelete() {
    if (!selectedId) return;
    const title = detail ? detail.title : selectedId;
    if (!window.confirm(`Delete "${title}" and remove its stored file from MinIO? This cannot be undone.`)) return;
    try {
      await api.deleteDocument(selectedId);
      setMessage({ kind: "ok", text: `Deleted "${title}".` });
      setSelectedId(null);
      setDetail(null);
      await refresh();
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    }
  }

  async function handleClearAll() {
    const count = documents.length;
    if (count === 0) {
      setMessage({ kind: "err", text: "Nothing to clear — no documents in the registry." });
      return;
    }
    if (!window.confirm(`Delete ALL ${count} documents, their chunks/embeddings and MinIO files? This cannot be undone.`)) return;
    try {
      const result = await api.clearDocuments();
      setMessage({
        kind: "ok",
        text: `Cleared ${result.deleted_documents} documents (${result.removed_objects} objects removed from MinIO).`,
      });
      setSelectedId(null);
      setDetail(null);
      await refresh();
    } catch (e) {
      setMessage({ kind: "err", text: e.message });
    }
  }

  const busyJobs = detail
    ? detail.versions.flatMap((v) =>
        v.ingestion_jobs.filter((j) => j.status === "PENDING" || j.status === "PROCESSING")
      )
    : [];

  return (
    <>
      <h1>Document Ingestion</h1>
      <p className="subtitle">
        Upload HR documents — the worker parses, chunks, embeds and indexes them; then
        they become searchable in the Knowledge Service.
      </p>

      <div className="grid">
        <section className="card">
          <h2>Upload document</h2>
          <form onSubmit={handleUpload}>
            <label htmlFor="file">File (pdf, docx, md, …)</label>
            <input
              id="file"
              type="file"
              accept=".md,.pdf,.docx,.doc,.txt,.pptx,.xlsx,text/markdown,application/pdf"
              onChange={(e) => setFile(e.target.files[0] || null)}
            />
            <label htmlFor="category">Category</label>
            <select id="category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <label htmlFor="docType">Document type</label>
            <input
              id="docType"
              type="text"
              value={docType}
              placeholder="e.g. policy, procedure, form"
              onChange={(e) => setDocType(e.target.value)}
            />
            <label htmlFor="description">Description (optional)</label>
            <textarea
              id="description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="actions" style={{ marginTop: 14 }}>
              <button className="primary" type="submit" disabled={uploading}>
                {uploading ? "Uploading…" : "Upload & index"}
              </button>
              {busyJobs.length > 0 && (
                <span className="badge busy">indexing in progress…</span>
              )}
            </div>
          </form>
        </section>

        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>Document registry</h2>
            {documents.length > 0 && (
              <button className="danger" onClick={handleClearAll}>
                Clear all
              </button>
            )}
          </div>
          {documents.length === 0 ? (
            <p className="muted">No documents yet — upload one to get started.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Versions</th>
                  <th>Chunks</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr
                    key={d.document_id}
                    className="clickable"
                    onClick={() => {
                      setSelectedId(d.document_id);
                      loadDetail(d.document_id);
                    }}
                  >
                    <td>
                      {d.title}
                      {d.document_id === selectedId && <span className="muted"> ✓</span>}
                    </td>
                    <td>{d.category}</td>
                    <td>
                      <span className={statusClass(d.status)}>{d.status}</span>
                    </td>
                    <td>{d.versions}</td>
                    <td>{d.current_chunks}</td>
                    <td className="small muted">{fmtDate(d.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      {message && (
        <div className={message.kind === "ok" ? "success" : "error"}>{message.text}</div>
      )}

      {detail && (
        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>
              {detail.title} <span className="badge">{detail.category}</span>{" "}
              <span className={statusClass(detail.status)}>{detail.status}</span>
            </h2>
            <button onClick={() => loadDetail(selectedId)}>Refresh</button>
            <button className="danger" onClick={handleDelete}>
              Delete document
            </button>
          </div>
          {detail.versions.map((v) => (
            <div key={v.document_version_id} style={{ marginTop: 14 }}>
              <h3 className="small muted" style={{ margin: "0 0 6px" }}>
                v{v.version_number}
                {v.is_current ? " (current)" : ""} · {fmtDate(v.uploaded_at)} ·{" "}
                {v.original_filename} · <code>{v.checksum.slice(0, 12)}</code>
              </h3>
              {v.change_summary && (
                <p className="small muted" style={{ margin: "0 0 6px" }}>
                  change summary: <code>{v.change_summary}</code>
                </p>
              )}
              {v.ingestion_jobs.length === 0 ? (
                <p className="small muted">no ingestion job for this version</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Status</th>
                      <th>Failure</th>
                      <th>Parser / Chunker / Embedder</th>
                      <th>Completed</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {v.ingestion_jobs.map((j) => (
                      <tr key={j.ingestion_job_id}>
                        <td>
                          <code>{shortId(j.ingestion_job_id)}</code>
                        </td>
                        <td>
                          <span className={statusClass(j.status)}>{j.status}</span>
                        </td>
                        <td className="small muted">
                          {j.failure_reason || "—"}
                          {j.error_message && <div>{j.error_message}</div>}
                        </td>
                        <td className="small muted">
                          {[j.parser_version, j.chunking_strategy, j.embedding_model]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </td>
                        <td className="small muted">{fmtDate(j.completed_at)}</td>
                        <td>
                          {j.status === "FAILED" && (
                            <button
                              className="small"
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
              )}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
