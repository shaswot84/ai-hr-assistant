"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { KnowledgeSearchResult } from "@/lib/types";
import { shortId } from "@/lib/format";

const CATEGORIES = [
  "",
  "POLICY",
  "PROCEDURE",
  "GUIDELINE",
  "FORM",
  "TEMPLATE",
  "TRAINING_MATERIAL",
  "OTHER",
];

function AnswerBlock({ result }: { result: KnowledgeSearchResult }) {
  if (result.answer) {
    return (
      <div className="space-y-2">
        {result.answer.split("\n").map((line, i) => {
          const trimmed = line.trim();
          if (!trimmed) return <div key={i} className="h-2" />;
          if (/^[-*]\s+/.test(trimmed)) {
            return (
              <li key={i} className="ml-5 list-disc">
                {trimmed.replace(/^[-*]\s+/, "")}
              </li>
            );
          }
          return (
            <p key={i} className="text-sm leading-relaxed text-gray-800">
              {line}
            </p>
          );
        })}
      </div>
    );
  }

  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-sm text-gray-700">
      {result.grounded_context || "(no grounded context)"}
    </pre>
  );
}

export function KnowledgeChat() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [topK, setTopK] = useState("");
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<KnowledgeSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || searching) return;

    setSearching(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.search({
        q,
        category: category || undefined,
        top_k: topK ? Number(topK) : undefined,
        generate: true,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Search failed. Is the backend running?");
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSearch} className="card p-4">
        <div className="flex flex-col gap-3 lg:flex-row">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about HR policy, benefits, leave…"
            className="input flex-1"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="input w-full lg:w-48"
            aria-label="Category filter"
          >
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
            placeholder="Top K"
            value={topK}
            onChange={(e) => setTopK(e.target.value)}
            className="input w-full lg:w-24"
            aria-label="Top K results"
          />
          <button type="submit" disabled={searching || !query.trim()} className="btn-primary">
            {searching ? (
              <>
                <span
                  aria-hidden="true"
                  className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                />
                Searching…
              </>
            ) : (
              "Ask"
            )}
          </button>
        </div>
        {searching && (
          <p className="mt-3 text-xs text-gray-400">
            Retrieving evidence, reranking, and generating a grounded answer — this can take a few
            seconds.
          </p>
        )}
      </form>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <>
          <section className="card p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-bold text-gray-900">Grounded answer</h2>
              <div className="flex items-center gap-2">
                {result.low_confidence && (
                  <span className="badge bg-red-100 text-red-700">low confidence</span>
                )}
                <span className="badge bg-blue-100 text-blue-700">
                  confidence {result.confidence}
                </span>
              </div>
            </div>

            <AnswerBlock result={result} />

            {result.citations.length > 0 && (
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-gray-400">citations:</span>
                {result.citations.map((c) => (
                  <span key={c.chunk_id} className="badge bg-gray-100 text-gray-600">
                    {c.document_title}
                    {c.section_title ? ` › ${c.section_title}` : ""} (v{c.version_number})
                  </span>
                ))}
              </div>
            )}
          </section>

          <section className="card overflow-hidden">
            <div className="border-b border-gray-100 px-6 py-4">
              <h2 className="text-lg font-bold text-gray-900">
                Retrieved chunks{" "}
                <span className="ml-1 text-sm font-normal text-gray-400">
                  ({result.chunks.length})
                </span>
              </h2>
            </div>

            {result.chunks.length === 0 ? (
              <p className="px-6 py-12 text-center text-sm text-gray-400">
                No chunks retrieved.
              </p>
            ) : (
              <div className="divide-y divide-gray-100">
                {result.chunks.map((c) => (
                  <div key={c.chunk_id} className="px-6 py-4">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="text-sm text-gray-900">{c.document_title}</strong>
                        {c.section_title && (
                          <span className="text-xs text-gray-400">› {c.section_title}</span>
                        )}
                        <span className="badge bg-blue-50 text-blue-700">{c.category}</span>
                      </div>
                      <span className="text-xs text-gray-400">
                        retr {c.retrieval_score} · rerank{" "}
                        {c.reranker_score === null ? "—" : c.reranker_score} · conf {c.confidence}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700">{c.text}</p>
                    <div className="mt-2 text-xs text-gray-400">
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
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
