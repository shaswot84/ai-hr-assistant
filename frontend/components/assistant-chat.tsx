"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, api, chatStream } from "@/lib/api";
import type { ChatCitation, ChatConversation } from "@/lib/types";

interface ViewMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations: ChatCitation[] | null;
  meta: {
    agent?: string;
    confidence?: number;
    low_confidence?: boolean;
    confidence_applicable?: boolean;
    safety?: "PASS" | "REDACTED" | "BLOCKED" | "FLAGGED_FOR_REVIEW";
  } | null;
  streaming?: boolean;
}

const AGENT_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  leave: "Leave",
  recruitment: "Recruitment",
  clarify: "Clarify",
};

/** Markdown renderer shared by assistant bubbles (same styles as knowledge-chat). */
function Markdown({ children }: { children: string }) {
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
        {children}
      </ReactMarkdown>
    </div>
  );
}

function CitationChips({ citations }: { citations: ChatCitation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">Sources</span>
      {citations.map((c) => (
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
  );
}

function MessageBubble({ message }: { message: ViewMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-blue-600 px-4 py-2.5 text-sm text-white shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  const lowConfidence = message.meta?.low_confidence ?? false;
  const confidence = message.meta?.confidence ?? 0;
  // Non-retrieval agents (leave/recruitment/clarify/recap) have no retrieval
  // confidence — the backend marks it not-applicable. Older transcripts
  // without the flag fall back to "confidence > 0" (knowledge turns always
  // carry a real confidence, transactional turns are 0.0).
  const confidenceApplicable = message.meta?.confidence_applicable ?? confidence > 0;
  // Only render an agent badge for agents we know about — "unknown" (or an
  // old persisted label) must never surface as a badge.
  const agentLabel = message.meta?.agent ? AGENT_LABELS[message.meta.agent] : undefined;
  const showMeta =
    confidenceApplicable ||
    lowConfidence ||
    message.meta?.safety === "FLAGGED_FOR_REVIEW" ||
    agentLabel !== undefined;
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-zinc-200 bg-white px-4 py-3 shadow-sm">
        {message.content ? (
          <Markdown>{message.content}</Markdown>
        ) : (
          <span className="text-zinc-400">Thinking…</span>
        )}
        {message.streaming && message.content && (
          <span
            aria-hidden="true"
            className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-[2px] bg-blue-500 align-text-bottom"
          />
        )}
        <CitationChips citations={message.citations ?? []} />
        {showMeta && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {confidence > 0 && (
              <span className="badge bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">
                confidence {confidence.toFixed(2)}
              </span>
            )}
            {lowConfidence && (
              <span className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20">
                low confidence
              </span>
            )}
            {message.meta?.safety === "FLAGGED_FOR_REVIEW" && (
              <span
                title="Some claims could not be verified against the sources."
                className="badge bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20"
              >
                claims flagged for review
              </span>
            )}
            {agentLabel && (
              <span className="badge bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20">
                {agentLabel}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function conversationDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Multi-turn assistant chat: conversation history, streaming answers with
 * citations, and low-confidence honesty — wired to the supervisor graph via
 * `POST /api/chat/stream`.
 */
export function AssistantChat() {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const refreshConversations = useCallback(() => {
    api.listConversations().then(setConversations).catch(() => {});
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function selectConversation(id: string) {
    if (streaming) return;
    setActiveId(id);
    setLoadingHistory(true);
    setError(null);
    try {
      const rows = await api.listChatMessages(id);
      setMessages(
        rows.map((m) => ({
          id: m.message_id,
          role: m.role,
          content: m.content,
          citations: m.citations,
          meta: m.meta,
        }))
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to load conversation.");
    } finally {
      setLoadingHistory(false);
    }
  }

  function newChat() {
    if (streaming) return;
    abortRef.current?.abort();
    setActiveId(null);
    setMessages([]);
    setInput("");
    setError(null);
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setError(null);

    const userMessage: ViewMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      citations: null,
      meta: null,
    };
    const assistantId = `local-assistant-${Date.now()}`;
    setMessages((m) => [
      ...m,
      userMessage,
      { id: assistantId, role: "assistant", content: "", citations: null, meta: null, streaming: true },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);

    let textSoFar = "";
    let citations: ChatCitation[] = [];
    let confidence = 0;
    let lowConfidence = false;
    let confidenceApplicable = false;
    let agent = "knowledge";
    let sawTurnStarted = false;

    const patchAssistant = (patch: Partial<ViewMessage>) =>
      setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)));

    try {
      for await (const event of chatStream(
        { conversation_id: activeId ?? undefined, message: text },
        controller.signal
      )) {
        if (event.type === "turn_started") {
          sawTurnStarted = true;
          setActiveId(event.conversation_id);
        } else if (event.type === "route") {
          agent = event.route;
        } else if (event.type === "retrieval") {
          citations = event.citations;
          confidence = event.confidence;
          lowConfidence = event.low_confidence;
        } else if (event.type === "token" || event.type === "message") {
          textSoFar += event.text;
          patchAssistant({ content: textSoFar });
        } else if (event.type === "done") {
          agent = event.agent;
          citations = event.citations;
          confidence = event.confidence;
          lowConfidence = event.low_confidence;
          confidenceApplicable = event.confidence_applicable;
          textSoFar = event.message || textSoFar;
          if (sawTurnStarted) setActiveId(event.conversation_id);
          patchAssistant({
            content: textSoFar,
            citations,
            meta: { agent, confidence, low_confidence: lowConfidence, confidence_applicable: confidenceApplicable },
            streaming: false,
          });
        } else if (event.type === "error") {
          setError(event.detail);
        }
      }
    } catch (err) {
      if (!(err instanceof Error && err.name === "AbortError")) {
        const detail =
          err instanceof ApiError ? err.detail : "Chat failed. Is the backend running?";
        setError(detail);
        patchAssistant({ streaming: false, content: textSoFar || "…" });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      refreshConversations();
    }
  }

  return (
    <div className="card flex h-[calc(100vh-16rem)] min-h-[420px] overflow-hidden">
      {/* Conversation list (desktop) */}
      <aside className="hidden w-72 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50/60 lg:flex">
        <div className="border-b border-zinc-200 p-3">
          <button
            type="button"
            onClick={newChat}
            disabled={streaming}
            className="btn-primary w-full"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New chat
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {conversations.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-zinc-400">
              No conversations yet — ask your first question.
            </p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((c) => (
                <li key={c.conversation_id}>
                  <button
                    type="button"
                    onClick={() => selectConversation(c.conversation_id)}
                    className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                      c.conversation_id === activeId
                        ? "bg-blue-600 text-white"
                        : "text-zinc-700 hover:bg-zinc-100"
                    }`}
                  >
                    <span className="block truncate text-[13px] font-medium">
                      {c.title ?? "Untitled chat"}
                    </span>
                    <span
                      className={`block text-[11px] ${
                        c.conversation_id === activeId ? "text-blue-100" : "text-zinc-400"
                      }`}
                    >
                      {conversationDate(c.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      {/* Chat thread */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Mobile conversation switcher */}
        <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 lg:hidden">
          <select
            value={activeId ?? ""}
            onChange={(e) => (e.target.value ? selectConversation(e.target.value) : newChat())}
            className="input flex-1"
            aria-label="Conversation"
          >
            <option value="">New chat</option>
            {conversations.map((c) => (
              <option key={c.conversation_id} value={c.conversation_id}>
                {c.title ?? "Untitled chat"}
              </option>
            ))}
          </select>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
          {messages.length === 0 && !loadingHistory && (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-white">
                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                  />
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-zinc-800">How can I help?</h3>
                <p className="mx-auto mt-1 max-w-sm text-xs text-zinc-500">
                  Ask about HR policy, benefits, leave, or open roles — answers are grounded in the
                  company knowledge base and remember the conversation.
                </p>
              </div>
            </div>
          )}

          {loadingHistory && (
            <div className="flex items-center justify-center py-10">
              <span className="text-xs text-zinc-400">Loading conversation…</span>
            </div>
          )}

          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div className="mx-4 mb-2 notice border-red-200 bg-red-50 text-red-700">{error}</div>
        )}

        <form onSubmit={handleSend} className="border-t border-zinc-200 p-3 sm:p-4">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              rows={1}
              placeholder="Ask about HR policy, leave, vacancies…"
              disabled={streaming}
              className="input max-h-40 min-h-[44px] flex-1 resize-y"
              aria-label="Message"
            />
            {streaming ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="btn-secondary shrink-0"
              >
                <span aria-hidden="true" className="h-3 w-3 rounded-[2px] bg-current" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="btn-primary shrink-0"
                aria-label="Send"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 12h14m-7-7l7 7-7 7"
                  />
                </svg>
              </button>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
