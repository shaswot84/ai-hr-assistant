"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
      <div className="text-sm leading-relaxed text-zinc-700">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p className="my-1.5">{children}</p>,
            ul: ({ children }) => (
              <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
            ),
            ol: ({ children }) => (
              <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
            ),
            li: ({ children }) => <li>{children}</li>,
            strong: ({ children }) => (
              <strong className="font-semibold text-zinc-900">{children}</strong>
            ),
            em: ({ children }) => <em>{children}</em>,
            h1: ({ children }) => (
              <h1 className="mb-2 mt-4 text-lg font-bold text-zinc-900">{children}</h1>
            ),
            h2: ({ children }) => (
              <h2 className="mb-2 mt-4 text-base font-bold text-zinc-900">{children}</h2>
            ),
            h3: ({ children }) => (
              <h3 className="mb-2 mt-3 text-sm font-bold text-zinc-900">{children}</h3>
            ),
            blockquote: ({ children }) => (
              <blockquote className="my-2 border-l-4 border-zinc-200 pl-3 text-zinc-500">
                {children}
              </blockquote>
            ),
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 underline">
                {children}
              </a>
            ),
            code: ({ children }) => (
              <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs">{children}</code>
            ),
          }}
        >
          {result.answer}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-50 p-4 font-mono text-[13px] leading-relaxed text-zinc-600">
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
    <div className="space-y-4">
      {/* Ask bar */}
      <form onSubmit={handleSearch} className="card p-3">
        <div className="flex flex-col gap-2 lg:flex-row">
          <div className="relative flex-1">
            <svg
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask about HR policy, benefits, leave…"
              className="input pl-9"
            />
          </div>
          <div className="flex gap-2">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="input w-full lg:w-44"
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
              className="input w-20 lg:w-20"
              aria-label="Top K results"
            />
            <button type="submit" disabled={searching || !query.trim()} className="btn-primary shrink-0">
              {searching ? (
                <>
                  <span
                    aria-hidden="true"
                    className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                  />
                  Searching…
                </>
              ) : (
                <>
                  Ask
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14m-7-7l7 7-7 7" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>
        {searching && (
          <p className="mt-2.5 flex items-center gap-2 text-xs text-zinc-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
            Retrieving evidence, reranking, and generating a grounded answer — this can take a few seconds.
          </p>
        )}
      </form>

      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}

      {result && (
        <>
          {/* Grounded answer */}
          <section className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 bg-zinc-50/60 px-5 py-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-600 text-white">
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2.5}
                      d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"
                    />
                  </svg>
                </span>
                <h2 className="text-sm font-semibold text-zinc-900">Grounded answer</h2>
              </div>
              <div className="flex items-center gap-2">
                {result.low_confidence && (
                  <span className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20">low confidence</span>
                )}
                <span className="badge bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">
                  confidence {result.confidence}
                </span>
              </div>
            </div>
            <div className="px-5 py-4">
              <AnswerBlock result={result} />
            </div>

            {result.citations.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 px-5 py-3">
                <span className="text-xs font-medium uppercase tracking-wider text-zinc-400">Sources</span>
                {result.citations.map((c) => (
                  <span
                    key={c.chunk_id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-600"
                  >
                    <svg className="h-3 w-3 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      />
                    </svg>
                    {c.document_title}
                    {c.section_title ? ` › ${c.section_title}` : ""}
                    <span className="text-zinc-400">v{c.version_number}</span>
                  </span>
                ))}
              </div>
            )}
          </section>

          {/* Retrieved chunks */}
          <section className="card overflow-hidden">
            <div className="border-b border-zinc-100 px-5 py-3">
              <h2 className="text-sm font-semibold text-zinc-900">
                Retrieved chunks{" "}
                <span className="ml-1 text-xs font-normal text-zinc-400">({result.chunks.length})</span>
              </h2>
            </div>

            {result.chunks.length === 0 ? (
              <p className="px-5 py-12 text-center text-sm text-zinc-400">No chunks retrieved.</p>
            ) : (
              <div className="divide-y divide-zinc-100">
                {result.chunks.map((c) => (
                  <details key={c.chunk_id} className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-3 transition-colors hover:bg-zinc-50 [&::-webkit-details-marker]:hidden">
                      <svg
                        className="h-4 w-4 shrink-0 text-zinc-400 transition-transform group-open:rotate-90"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                      <span className="block min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-zinc-800">
                          {c.document_title}
                        </span>
                        <span className="block text-[11px] text-zinc-400">
                          {c.category}
                          {c.section_title ? ` › ${c.section_title}` : ""} · v{c.version_number}
                        </span>
                      </span>
                      <span className="shrink-0 text-[11px] tabular-nums text-zinc-400">
                        retr {c.retrieval_score.toFixed(2)}
                        {c.reranker_score !== null ? ` · rerank ${c.reranker_score.toFixed(2)}` : ""}
                      </span>
                    </summary>
                    <div className="px-5 pb-4 pl-12">
                      <p className="text-[13px] leading-relaxed text-zinc-600">{c.text}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-zinc-400">
                        <code>{shortId(c.chunk_id)}</code>
                        <span>page {c.page ?? "—"}</span>
                        <span>conf {c.confidence}</span>
                        {c.provenance &&
                          [c.provenance.parser_version, c.provenance.chunking_strategy, c.provenance.embedding_model]
                            .filter(Boolean)
                            .join(" · ")}
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
