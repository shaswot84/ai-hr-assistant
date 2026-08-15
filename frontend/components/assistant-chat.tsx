"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, api, chatStream } from "@/lib/api";
import type { ChatCitation, ChatConversation } from "@/lib/types";
import { ChatWidgetRenderer } from "./chat-widgets";
import { useSidebar } from "./sidebar-provider";

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
    ui_widget?: any;
  } | null;
  streaming?: boolean;
  /** Live status of an in-flight answer (transient — never persisted): the
   * RAG retrieval phase, then LLM generation. Absent = thinking/routing. */
  phase?: "searching" | "generating";
}

const AGENT_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  leave: "Leave",
  recruitment: "Recruitment",
  clarify: "Clarify",
  recap: "Summary",
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
          li: ({ children }) => <li className="my-0.5">{children}</li>,
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
            <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-xs text-zinc-800">
              {children}
            </code>
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
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-zinc-100 pt-2.5">
      <span className="text-[11px] font-medium text-zinc-600">Sources:</span>
      {citations.map((c) => {
        const pageLabel = c.page ? ` p.${c.page}` : "";
        const sectionLabel = c.section_title ? ` · ${c.section_title}` : "";
        return (
          <span
            key={c.chunk_id}
            title={`${c.document_title} (v${c.version_number})${pageLabel}${sectionLabel}`}
            className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-700 hover:bg-zinc-200"
          >
            <span className="font-medium text-zinc-900 truncate max-w-[140px]">
              {c.document_title}
            </span>
            {pageLabel && <span className="text-zinc-600">{pageLabel}</span>}
          </span>
        );
      })}
    </div>
  );
}

const MessageBubble = memo(function MessageBubble({
  message,
  onAction,
  disabled,
}: {
  message: ViewMessage;
  onAction?: (actionText: string) => void;
  disabled?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable (non-secure context); ignore
    }
  }

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
  const confidenceApplicable = message.meta?.confidence_applicable ?? confidence > 0;
  const agentLabel = message.meta?.agent ? AGENT_LABELS[message.meta.agent] : undefined;
  const showMeta =
    confidenceApplicable ||
    lowConfidence ||
    message.meta?.safety === "FLAGGED_FOR_REVIEW" ||
    agentLabel !== undefined;
  return (
    <div className="group relative flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-zinc-200 bg-white px-4 py-3 shadow-sm">
        {message.content && !message.streaming && (
          <button
            type="button"
            onClick={handleCopy}
            className={`absolute right-2 top-2 rounded-md p-1.5 transition-opacity ${
              copied
                ? "text-green-600 opacity-100"
                : "text-zinc-400 opacity-0 hover:bg-zinc-100 hover:text-zinc-700 group-hover:opacity-100 focus:opacity-100"
            }`}
            aria-label={copied ? "Copied" : "Copy message"}
            title={copied ? "Copied" : "Copy message"}
          >
            {copied ? (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
            )}
          </button>
        )}
        {message.content ? (
          /* While streaming, render plain text so markdown isn't re-parsed on
             every token; switch to the full renderer once the turn finishes. */
          message.streaming ? (
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-700">
              {message.content}
            </div>
          ) : (
            <Markdown>{message.content}</Markdown>
          )
        ) : (
          /* Staged live status — only while the answer is actually streaming
             (a restored empty message must never look like it is thinking
             forever). Absent phase = thinking/routing. */
          message.streaming && !message.meta?.ui_widget && (
            message.phase === "searching" ? (
              <span
                className="flex items-center gap-2 py-1 text-sm text-zinc-500"
                aria-label="Searching the knowledge base"
              >
                <svg
                  className="h-3.5 w-3.5 animate-spin text-blue-500"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Searching the knowledge base…
              </span>
            ) : message.phase === "generating" ? (
              <span
                className="flex items-center gap-1.5 py-1 text-sm text-zinc-500"
                aria-label="Generating response"
              >
                Generating…
                <span
                  aria-hidden="true"
                  className="inline-block h-3.5 w-[2px] animate-blink rounded-[1px] bg-blue-500"
                />
              </span>
            ) : (
              <span className="flex items-center gap-1.5 py-1 text-sm text-zinc-500" aria-label="Thinking">
                <span className="h-1.5 w-1.5 animate-bounce-dot rounded-full bg-zinc-400" />
                <span
                  className="h-1.5 w-1.5 animate-bounce-dot rounded-full bg-zinc-400"
                  style={{ animationDelay: "150ms" }}
                />
                <span
                  className="h-1.5 w-1.5 animate-bounce-dot rounded-full bg-zinc-400"
                  style={{ animationDelay: "300ms" }}
                />
                Thinking…
              </span>
            )
          )
        )}
        {message.streaming && message.content && (
          <span
            aria-hidden="true"
            className="ml-0.5 inline-block h-3.5 w-[2px] animate-blink rounded-[1px] bg-blue-500 align-text-bottom"
          />
        )}

        {message.meta?.ui_widget && (
          <ChatWidgetRenderer
            widget={message.meta.ui_widget}
            onAction={onAction}
            disabled={disabled}
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
});

/** Local title for a brand-new conversation, mirroring the backend's
 * first-message-derived title (truncated at 80 chars). */
function localTitleFromMessage(text: string) {
  return text.length <= 80 ? text : `${text.slice(0, 80)}…`;
}

/** ChatGPT-style relative label for a conversation's last activity. */
function conversationTime(iso: string) {
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  if (hours < 48) return "Yesterday";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Draft persistence — typed input survives refresh/navigation. Drafts are
 * keyed per conversation (plus "new" for a fresh chat), and the last open
 * conversation is remembered so it can be restored together with its draft. */
const DRAFT_STORAGE_KEY = "aha.chat.drafts";
const LAST_ACTIVE_KEY = "aha.chat.lastActive";

function readDrafts(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function writeDraft(key: string, value: string) {
  try {
    const drafts = readDrafts();
    if (value) drafts[key] = value;
    else delete drafts[key];
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(drafts));
  } catch {
    // localStorage unavailable — persistence is best-effort
  }
}

export function AssistantChat() {
  const { collapsed } = useSidebar();
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [atBottom, setAtBottom] = useState(true);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const skipHistoryFetchRef = useRef<string | null>(null);
  const historyRef = useRef<HTMLDivElement | null>(null);
  const sendMessageRef = useRef<typeof sendMessage>(sendMessage);
  // Conversations this session already auto-recovered (see recovery effect
  // below) — prevents a failed regeneration from looping.
  const recoveredRef = useRef<Set<string>>(new Set());

  const refreshConversations = useCallback(async () => {
    try {
      const list = await api.listConversations();
      // The API already orders by last activity, but sort here too so the
      // rail is always most-recent-first regardless of backend behavior.
      setConversations(
        [...list].sort(
          (a, b) =>
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() ||
            b.conversation_id.localeCompare(a.conversation_id)
        )
      );
    } catch {
      // offline / not authed; keep current
    }
  }, []);

  /** Update the rail in place after a turn — bump the active conversation's
   * updated_at (moving it to the top) or insert the brand-new conversation —
   * instead of refetching the whole list on every message. */
  const bumpConversation = useCallback((conversationId: string, title?: string) => {
    const now = new Date().toISOString();
    setConversations((prev) => {
      const exists = prev.some((c) => c.conversation_id === conversationId);
      const next = exists
        ? prev.map((c) =>
            c.conversation_id === conversationId ? { ...c, updated_at: now } : c
          )
        : [
            ...prev,
            {
              conversation_id: conversationId,
              title: title ?? null,
              created_at: now,
              updated_at: now,
            },
          ];
      return next.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() ||
          b.conversation_id.localeCompare(a.conversation_id)
      );
    });
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  // Close the collapsed-toolbar history dropdown on outside click / Escape.
  useEffect(() => {
    if (!historyOpen) return;
    function onPointerDown(e: MouseEvent | TouchEvent) {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setHistoryOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [historyOpen]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    if (skipHistoryFetchRef.current === activeId) {
      skipHistoryFetchRef.current = null;
      return;
    }
    let cancelled = false;
    setLoadingHistory(true);
    setError(null);
    api
      .listChatMessages(activeId)
      .then((history) => {
        if (cancelled) return;
        setMessages(
          history.map((m) => ({
            id: m.message_id,
            role: m.role as "user" | "assistant" | "system",
            content: m.content,
            citations: (m.citations as ChatCitation[]) ?? null,
            meta: (m.meta as ViewMessage["meta"]) ?? null,
          }))
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.detail : "Failed to load conversation.");
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // Draft persistence: reopen the last conversation and restore its typed
  // input, so a refresh/navigation doesn't wipe a half-typed question.
  const draftKey = activeId ?? "new";

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(LAST_ACTIVE_KEY);
    } catch {
      // ignore
    }
    if (saved) queueMicrotask(() => setActiveId(saved));
  }, []);

  useEffect(() => {
    try {
      if (activeId) localStorage.setItem(LAST_ACTIVE_KEY, activeId);
      else localStorage.removeItem(LAST_ACTIVE_KEY);
    } catch {
      // ignore
    }
  }, [activeId]);

  // Restore the draft whenever the active conversation changes (the initial
  // mount restores the "new chat" draft).
  useEffect(() => {
    const draft = readDrafts()[draftKey] ?? "";
    queueMicrotask(() => setInput(draft));
  }, [draftKey]);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, []);

  const isNearBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  // Keep the newest content in view while tokens stream in (and settle at the
  // bottom after history loads) — but never fight the user who scrolled up to
  // re-read an earlier message.
  useEffect(() => {
    if (isNearBottom()) scrollToBottom();
  }, [messages, streaming, scrollToBottom, isNearBottom]);

  // When a new answer starts generating, snap straight to it even if the user
  // was reading at the top or middle of the thread (ChatGPT-style follow).
  useEffect(() => {
    if (streaming) scrollToBottom();
  }, [streaming, scrollToBottom]);

  // Track whether the user is at the bottom of the thread. Content growth is
  // covered by the follow effect above (its scroll fires this handler), so the
  // chip only appears when the user actually scrolled up mid-stream.
  const handleScroll = useCallback(() => {
    setAtBottom(isNearBottom());
  }, [isNearBottom]);

  function selectConversation(id: string) {
    if (streaming) return;
    setActiveId(id);
  }

  function newChat() {
    if (streaming) abortRef.current?.abort();
    setActiveId(null);
    setMessages([]);
    setError(null);
    // The "new chat" draft is restored by the draft effect on activeId change.
  }

  async function handleDeleteConversation(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (streaming) return;
    try {
      await api.deleteConversation(id);
      writeDraft(id, "");
      setConversations((prev) => prev.filter((c) => c.conversation_id !== id));
      if (activeId === id) {
        newChat();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to delete conversation.");
    }
  }

  async function sendMessage(textToSend: string) {
    if (!textToSend.trim() || streaming) return;
    setInput("");
    writeDraft(activeId ?? "new", "");
    setError(null);

    const userMessage: ViewMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: textToSend,
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
    let uiWidget: any = null;
    let sawTurnStarted = false;
    const startedNewChat = activeId === null;
    let turnConversationId: string | null = null;

    const patchAssistant = (patch: Partial<ViewMessage>) =>
      setMessages((m) => m.map((msg) => (msg.id === assistantId ? { ...msg, ...patch } : msg)));

    try {
      for await (const event of chatStream(
        { conversation_id: activeId ?? undefined, message: textToSend },
        controller.signal
      )) {
        if (event.type === "turn_started") {
          sawTurnStarted = true;
          turnConversationId = event.conversation_id;
          skipHistoryFetchRef.current = event.conversation_id;
          setActiveId(event.conversation_id);
        } else if (event.type === "route") {
          agent = event.route;
          // Non-retrieval routes (recap/clarify/leave/recruitment) generate
          // the answer directly after routing — mark that stage. Knowledge
          // goes through retrieval first (handled below), then tokens.
          if (event.route !== "knowledge") patchAssistant({ phase: "generating" });
        } else if (event.type === "retrieval") {
          citations = event.citations;
          confidence = event.confidence;
          lowConfidence = event.low_confidence;
          patchAssistant({ phase: "searching" });
        } else if (event.type === "ui_widget") {
          uiWidget = event.widget;
          patchAssistant({
            meta: {
              agent,
              confidence,
              low_confidence: lowConfidence,
              confidence_applicable: confidenceApplicable,
              ui_widget: uiWidget,
            },
          });
        } else if (event.type === "token" || event.type === "message") {
          textSoFar += event.text;
          patchAssistant({ content: textSoFar, phase: "generating" });
        } else if (event.type === "done") {
          agent = event.agent;
          citations = event.citations;
          confidence = event.confidence;
          lowConfidence = event.low_confidence;
          confidenceApplicable = event.confidence_applicable;
          uiWidget = event.ui_widget || uiWidget;
          textSoFar = event.message || textSoFar;
          turnConversationId = event.conversation_id;
          if (sawTurnStarted) {
            skipHistoryFetchRef.current = event.conversation_id;
            setActiveId(event.conversation_id);
          }
          patchAssistant({
            content: textSoFar,
            citations,
            meta: {
              agent,
              confidence,
              low_confidence: lowConfidence,
              confidence_applicable: confidenceApplicable,
              ui_widget: uiWidget,
            },
            streaming: false,
          });
        } else if (event.type === "error") {
          setError(event.detail);
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        // User stopped the turn (Stop button, or leaving the page) — keep the
        // text streamed so far as the final message and drop the live
        // cursor/dots, otherwise the bubble stays "streaming" forever.
        patchAssistant({ streaming: false });
      } else {
        const detail =
          err instanceof ApiError ? err.detail : "Chat failed. Is the backend running?";
        setError(detail);
        patchAssistant({ streaming: false, content: textSoFar || "…" });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      // Update the rail locally instead of refetching the whole list.
      const convId = turnConversationId ?? activeId;
      if (convId) bumpConversation(convId, startedNewChat ? localTitleFromMessage(textToSend) : undefined);
    }
  }
  // Keep the ref pointed at the latest sendMessage closure (written in an
  // effect so handleAction can stay referentially stable for the memoized
  // bubbles).
  useEffect(() => {
    sendMessageRef.current = sendMessage;
  });

  // Abort any in-flight stream when the chat unmounts (navigating away), so
  // the backend stops generating an answer nobody will read.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Auto-recover conversations whose LAST assistant reply was persisted empty
  // (the pre-fix recap bug): re-ask the last user question so the answer
  // regenerates. Only attempts once per conversation and never mid-stream or
  // while history is still loading, so a failed regeneration can't loop. Placed
  // after the ref-update effect so the latest sendMessage (with the current
  // activeId in its closure) is used.
  useEffect(() => {
    if (streaming || loadingHistory || !activeId) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    if (last.content || last.meta?.ui_widget) return;
    const penultimate = messages[messages.length - 2];
    if (!penultimate || penultimate.role !== "user" || !penultimate.content.trim()) return;
    if (recoveredRef.current.has(activeId)) return;
    recoveredRef.current.add(activeId);
    sendMessageRef.current(penultimate.content);
  }, [messages, loadingHistory, streaming, activeId]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    await sendMessage(input);
  }

  // Stable identity so memoized bubbles don't re-render on unrelated updates;
  // the ref always points at the latest sendMessage (which guards streaming).
  const handleAction = useCallback((actionText: string) => {
    sendMessageRef.current(actionText);
  }, []);

  return (
    <div
      className={`card flex min-h-[420px] overflow-hidden ${
        collapsed ? "h-full" : "h-[calc(100vh-16rem)]"
      }`}
    >
      {/* Conversation list (desktop) — collapses with the portal sidebar so
          the chat thread takes the full width; stays mounted so the width
          change animates. */}
      <aside
        aria-hidden={collapsed}
        inert={collapsed ? true : undefined}
        className={`hidden h-full shrink-0 flex-col overflow-hidden border-r border-zinc-200 bg-zinc-50/60 transition-[width] duration-200 ease-out motion-reduce:transition-none lg:flex ${
          collapsed ? "w-0 border-r-0" : "w-72"
        }`}
      >
        <div className="flex h-full w-72 flex-col">
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
                {conversations.map((c) => {
                  const isActive = c.conversation_id === activeId;
                  return (
                    <li key={c.conversation_id} className="group relative">
                      <button
                        type="button"
                        onClick={() => selectConversation(c.conversation_id)}
                        className={`w-full rounded-lg px-3 py-2 pr-8 text-left transition-colors ${
                          isActive
                            ? "bg-blue-600 text-white"
                            : "text-zinc-700 hover:bg-zinc-100"
                        }`}
                      >
                        <span className="block truncate text-[13px] font-medium">
                          {c.title ?? "Untitled chat"}
                        </span>
                        <span
                          className={`block text-[11px] ${
                            isActive ? "text-blue-100" : "text-zinc-400"
                          }`}
                        >
                          {conversationTime(c.updated_at)}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteConversation(c.conversation_id, e)}
                        title="Delete conversation"
                        aria-label="Delete conversation"
                        className={`absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-xs opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 ${
                          isActive
                            ? "text-blue-200 hover:bg-blue-700 hover:text-white"
                            : "text-zinc-400 hover:bg-zinc-200 hover:text-red-600"
                        }`}
                      >
                        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </aside>

      {/* Chat thread */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Desktop: keep chat actions reachable when the conversation rail is
            collapsed (portal sidebar closed). */}
        {collapsed && (
          <div ref={historyRef} className="relative hidden items-center gap-2 border-b border-zinc-200 px-3 py-2 lg:flex">
            <button
              type="button"
              onClick={() => {
                setHistoryOpen(false);
                newChat();
              }}
              disabled={streaming}
              className="btn-primary"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New chat
            </button>

            <button
              type="button"
              onClick={() => setHistoryOpen((o) => !o)}
              disabled={streaming}
              aria-haspopup="listbox"
              aria-expanded={historyOpen}
              title="Conversation history"
              className="ml-auto inline-flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <span className="truncate">
                {activeId
                  ? (conversations.find((c) => c.conversation_id === activeId)?.title ?? "Untitled chat")
                  : "Conversation history"}
              </span>
              <svg className="h-3.5 w-3.5 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {activeId && (
              <button
                type="button"
                onClick={(e) => {
                  handleDeleteConversation(activeId, e);
                  setHistoryOpen(false);
                }}
                title="Delete conversation"
                aria-label="Delete conversation"
                className="rounded p-2 text-zinc-500 hover:bg-zinc-100 hover:text-red-600"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                  />
                </svg>
              </button>
            )}

            {historyOpen && (
              <div
                role="listbox"
                aria-label="Conversation history"
                className="absolute left-0 top-full z-20 mt-1 w-80 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg"
              >
                <div className="max-h-72 overflow-y-auto p-1.5">
                  {conversations.length === 0 ? (
                    <p className="px-3 py-6 text-center text-xs text-zinc-400">
                      No conversations yet — ask your first question.
                    </p>
                  ) : (
                    <ul className="space-y-0.5">
                      {conversations.map((c) => {
                        const isActive = c.conversation_id === activeId;
                        return (
                          <li key={c.conversation_id} className="group relative">
                            <button
                              type="button"
                              onClick={() => {
                                selectConversation(c.conversation_id);
                                setHistoryOpen(false);
                              }}
                              className={`w-full rounded-md px-2.5 py-2 pr-8 text-left transition-colors ${
                                isActive
                                  ? "bg-blue-600 text-white"
                                  : "text-zinc-700 hover:bg-zinc-100"
                              }`}
                            >
                              <span className="block truncate text-[13px] font-medium">
                                {c.title ?? "Untitled chat"}
                              </span>
                              <span
                                className={`block text-[11px] ${
                                  isActive ? "text-blue-100" : "text-zinc-400"
                                }`}
                              >
                              {conversationTime(c.updated_at)}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              handleDeleteConversation(c.conversation_id, e);
                              setHistoryOpen(false);
                            }}
                              title="Delete conversation"
                              aria-label="Delete conversation"
                              className={`absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-xs opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100 ${
                                isActive
                                  ? "text-blue-200 hover:bg-blue-700 hover:text-white"
                                  : "text-zinc-400 hover:bg-zinc-200 hover:text-red-600"
                              }`}
                            >
                              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                />
                              </svg>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

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
          {activeId && (
            <button
              type="button"
              onClick={(e) => handleDeleteConversation(activeId, e)}
              title="Delete conversation"
              aria-label="Delete conversation"
              className="rounded p-2 text-zinc-500 hover:bg-zinc-100 hover:text-red-600"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
            </button>
          )}
        </div>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="relative flex-1 space-y-4 overflow-y-auto p-4 sm:p-5"
        >
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

          {messages.map((m, idx) => (
            <MessageBubble
              key={m.id}
              message={m}
              onAction={handleAction}
              // Freeze widgets in PAST turns (any message that is not the
              // last one): once the conversation has moved past a widget it
              // must not be operated again. The current (last) widget stays
              // interactive, and while an answer streams the whole thread is
              // disabled via `streaming` as before.
              disabled={streaming || idx < messages.length - 1}
            />
          ))}

          {!atBottom && (
            <button
              type="button"
              onClick={scrollToBottom}
              className="animate-slide-up absolute bottom-4 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 shadow-sm transition-colors hover:bg-zinc-50 hover:text-zinc-900"
              aria-label="Scroll to latest message"
              title="Scroll to latest message"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
              Scroll to latest
            </button>
          )}
        </div>

        {error && (
          <div className="mx-4 mb-2 notice border-red-200 bg-red-50 text-red-700">{error}</div>
        )}

        <form onSubmit={handleSend} className="border-t border-zinc-200 p-3 sm:p-4">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                writeDraft(activeId ?? "new", e.target.value);
              }}
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
