"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { shortId } from "@/lib/format";

const CATEGORIES = ["", "POLICY", "PROCEDURE", "GUIDELINE", "FORM", "TEMPLATE", "TRAINING_MATERIAL", "OTHER"];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [topK, setTopK] = useState("");
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function handleSearch(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    setResult(null);
    const params = { q: query.trim() };
    if (category) params.category = category;
    if (topK) params.top_k = topK;
    try {
      setResult(await api.search(params));
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  }

  return (
    <>
      <h1>Knowledge Search</h1>
      <p className="subtitle">
        Hybrid retrieval (BM25 + vector) over indexed documents, with RRF fusion,
        citations and confidence scoring.
      </p>

      <form className="card" onSubmit={handleSearch}>
        <div className="actions">
          <input
            type="text"
            style={{ flex: 1, minWidth: 260 }}
            placeholder="e.g. how many days of annual leave"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c ? `Category: ${c}` : "Any category"}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            max={50}
            placeholder="top k"
            style={{ width: 90 }}
            value={topK}
            onChange={(e) => setTopK(e.target.value)}
          />
          <button className="primary" type="submit" disabled={searching || !query.trim()}>
            {searching ? "Searching…" : "Search"}
          </button>
        </div>
      </form>

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <section className="card">
            <div className="row">
              <h2 style={{ margin: 0 }}>Grounded answer</h2>
              <div className="actions">
                {result.low_confidence && <span className="badge err">low confidence</span>}
                <span className="badge">confidence {result.confidence}</span>
              </div>
            </div>
            <pre>{result.grounded_context || "(no grounded context)"}</pre>
            {result.citations.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <span className="small muted">citations:</span>{" "}
                {result.citations.map((c) => (
                  <span key={c.chunk_id} className="chip">
                    {c.document_title}
                    {c.section_title ? ` › ${c.section_title}` : ""} (v{c.version_number})
                  </span>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <h2>
              Retrieved chunks <span className="muted small">({result.chunks.length})</span>
            </h2>
            {result.chunks.length === 0 && <p className="muted">No chunks retrieved.</p>}
            {result.chunks.map((c) => (
              <div
                key={c.chunk_id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  padding: "12px 14px",
                  marginBottom: 10,
                }}
              >
                <div className="row" style={{ marginBottom: 6 }}>
                  <span>
                    <strong>{c.document_title}</strong>
                    {c.section_title && <span className="muted"> › {c.section_title}</span>}
                    <span className="badge" style={{ marginLeft: 8 }}>
                      {c.category}
                    </span>
                  </span>
                  <span className="small muted">
                    retr {c.retrieval_score} · rerank{" "}
                    {c.reranker_score === null ? "—" : c.reranker_score} · conf {c.confidence}
                  </span>
                </div>
                <p style={{ margin: "4px 0" }}>{c.text}</p>
                <div className="small muted">
                  <code>{shortId(c.chunk_id)}</code> · page {c.page ?? "—"} · v{c.version_number}
                  {c.provenance && (
                    <>
                      {" · "}
                      {[c.provenance.parser_version, c.provenance.chunking_strategy, c.provenance.embedding_model]
                        .filter(Boolean)
                        .join(" · ")}
                    </>
                  )}
                </div>
              </div>
            ))}
          </section>
        </>
      )}
    </>
  );
}
