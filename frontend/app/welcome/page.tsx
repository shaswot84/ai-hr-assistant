"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ApiError, publicChatStream } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";
import type { ChatCitation } from "@/lib/types";
import { ChatWidgetRenderer } from "@/components/chat-widgets";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

interface ChatBubble {
  id: string;
  role: "assistant" | "user";
  text: string;
  citations?: ChatCitation[];
  ui_widget?: any;
  loading?: boolean;
}

const GREETING =
  "Hi! I can answer questions about company policy, benefits, and open job roles. Ask me what jobs are open, or explore vacancies below.";

const SUGGESTIONS = [
  "What jobs are open right now?",
  "How do I apply for a role?",
  "Tell me about the Data Analyst role",
  "What is the annual leave policy?",
];

function WelcomeCitationChips({ citations }: { citations: ChatCitation[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (citations.length === 0) return null;
  return (
    <div className="mt-3 border-t border-zinc-100 pt-2">
      <span className="text-[11px] font-semibold text-zinc-600">Sources:</span>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {citations.map((c, cIdx) => {
          const isOpen = expanded === `${c.chunk_id}-${cIdx}`;
          return (
            <span key={cIdx} className="relative">
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : `${c.chunk_id}-${cIdx}`)}
                className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-700 hover:bg-zinc-200 transition-colors"
              >
                <span className="truncate max-w-[140px] text-zinc-900">{c.document_title}</span>
                {c.page && <span className="text-zinc-600">p.{c.page}</span>}
                <svg className={`h-3 w-3 text-zinc-400 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
            </span>
          );
        })}
      </div>
      {/* Inline detail panel for the expanded citation */}
      {expanded && (() => {
        const c = citations.find((x) => `${x.chunk_id}-${citations.indexOf(x)}` === expanded);
        if (!c) return null;
        return (
          <div className="mt-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2.5 text-[11px] text-zinc-600">
            <div className="space-y-0.5">
              <div><span className="font-medium text-zinc-800">Document:</span> {c.document_title}</div>
              <div><span className="font-medium text-zinc-800">Version:</span> v{c.version_number}</div>
              <div><span className="font-medium text-zinc-800">Page:</span> {c.page ?? "—"}</div>
              <div><span className="font-medium text-zinc-800">Section:</span> {c.section_title || "—"}</div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-zinc-800">
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
          h1: ({ children }) => (
            <h1 className="mb-2 mt-3 text-base font-bold text-zinc-900">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-3 text-sm font-bold text-zinc-900">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1.5 mt-2 text-xs font-bold text-zinc-900 uppercase tracking-wide">{children}</h3>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-4 border-zinc-300 pl-3 text-zinc-600">
              {children}
            </blockquote>
          ),
          code: ({ children }) => (
            <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-xs text-zinc-800">
              {children}
            </code>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [messages, setMessages] = useState<ChatBubble[]>([
    { id: "greeting", role: "assistant", text: GREETING },
  ]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const token = getAuthToken();
    if (!token) {
      Promise.resolve().then(() => {
        if (!cancelled) setCheckingSession(false);
      });
      return () => {
        cancelled = true;
      };
    }
    api
      .me()
      .then((res) => {
        if (!cancelled) router.replace(ROLE_HOME[res.user.coarse_role] ?? "/candidate");
      })
      .catch(() => {
        if (!cancelled) setCheckingSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (checkingSession) return;
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, [checkingSession]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const userBubble: ChatBubble = {
      id: `${Date.now()}-u`,
      role: "user",
      text: trimmed,
    };

    const pendingAssistantBubble: ChatBubble = {
      id: `${Date.now()}-a`,
      role: "assistant",
      text: "",
      loading: true,
    };

    const newHistory = [...messages, userBubble];
    setMessages([...newHistory, pendingAssistantBubble]);
    setDraft("");
    setSending(true);

    const historyPayload = newHistory
      .filter((m) => m.id !== "greeting")
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.text }));

    try {
      let accumulatedText = "";
      let citations: ChatCitation[] = [];
      let uiWidget: any = undefined;

      for await (const event of publicChatStream({
        message: trimmed,
        history: historyPayload,
      })) {
        if (event.type === "retrieval") {
          citations = event.citations || [];
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? { ...m, citations }
                : m
            )
          );
        } else if (event.type === "token") {
          accumulatedText += event.text;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? { ...m, text: accumulatedText, loading: false }
                : m
            )
          );
        } else if (event.type === "message") {
          accumulatedText = event.text;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? { ...m, text: accumulatedText, loading: false }
                : m
            )
          );
        } else if (event.type === "ui_widget") {
          uiWidget = event.widget;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? { ...m, ui_widget: uiWidget, loading: false }
                : m
            )
          );
        } else if (event.type === "done") {
          if (event.message) accumulatedText = event.message;
          citations = event.citations || [];
          if (event.ui_widget) uiWidget = event.ui_widget;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? {
                    ...m,
                    text: accumulatedText,
                    citations,
                    ui_widget: uiWidget,
                    loading: false,
                  }
                : m
            )
          );
        } else if (event.type === "error") {
          accumulatedText = event.detail;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingAssistantBubble.id
                ? { ...m, text: accumulatedText, loading: false }
                : m
            )
          );
        }
      }
    } catch (err) {
      const errMsg =
        err instanceof ApiError
          ? err.detail
          : "Sorry, I ran into an issue getting that answer. Please try again.";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingAssistantBubble.id
            ? { ...m, text: errMsg, loading: false }
            : m
        )
      );
    } finally {
      setSending(false);
    }
  }

  function handleSend(e: React.FormEvent) {
    e.preventDefault();
    sendMessage(draft);
  }

  function handleAction(actionText: string) {
    sendMessage(actionText);
  }

  if (checkingSession) {
    return <div className="min-h-screen bg-zinc-50" />;
  }

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white shadow-xs">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 shadow-sm text-white">
              <svg className="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-zinc-900">AI HR Assistant</p>
              <p className="text-[11px] text-zinc-500">Recruitment & Policy Platform</p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <Link
              href="/candidate"
              className="hidden sm:inline-flex rounded-lg px-3 py-1.5 text-xs font-medium text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
            >
              Browse Careers
            </Link>
            <Link href="/signin" className="btn-primary text-xs py-1.5 px-3.5">
              Sign In
            </Link>
          </div>
        </div>
      </header>

      <main
        className={`mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-5 transition-all duration-500 ease-out sm:px-6 lg:py-8 ${
          mounted ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
        }`}
      >
        <div className="mb-4 text-center sm:text-left">
          <h1 className="text-xl font-bold tracking-tight text-zinc-900 sm:text-2xl">
            Ask about policy or open vacancies
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Explore open jobs, ask questions, or sign in to track applications and leave.
          </p>
        </div>

        {/* Suggestions chips */}
        <div className="mb-4 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s, idx) => (
            <button
              key={idx}
              type="button"
              disabled={sending}
              onClick={() => sendMessage(s)}
              className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-xs font-medium text-zinc-700 shadow-2xs hover:border-blue-300 hover:bg-blue-50/50 hover:text-blue-700 disabled:opacity-50 transition-all"
            >
              {s}
            </button>
          ))}
        </div>

        <div className="card flex flex-1 flex-col overflow-hidden min-h-[520px] shadow-sm">
          <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[92%] sm:max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-blue-600 text-white shadow-xs rounded-br-xs"
                      : "border border-zinc-200/80 bg-white text-zinc-800 shadow-2xs rounded-bl-xs"
                  }`}
                >
                  {m.loading ? (
                    <div className="flex items-center gap-2 text-zinc-500 py-0.5">
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-600" />
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-600 [animation-delay:0.2s]" />
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-600 [animation-delay:0.4s]" />
                      <span className="text-xs font-medium ml-1">Thinking…</span>
                    </div>
                  ) : m.role === "user" ? (
                    <span>{m.text}</span>
                  ) : (
                    <MarkdownContent content={m.text} />
                  )}

                  {/* Citations */}
                  {m.citations && m.citations.length > 0 && (
                    <WelcomeCitationChips citations={m.citations} />
                  )}
                </div>

                {/* Interactive Recruitment Widgets */}
                {m.ui_widget && (
                  <div className="w-full max-w-[92%] sm:max-w-[85%]">
                    <ChatWidgetRenderer
                      widget={m.ui_widget}
                      onAction={handleAction}
                      disabled={sending}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>

          <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-zinc-200 bg-zinc-50/70 p-3 sm:p-4">
            <input
              type="text"
              value={draft}
              disabled={sending}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about policy, vacancies, or how to apply…"
              className="input flex-1 bg-white"
            />
            <button
              type="submit"
              className="btn-primary shrink-0"
              disabled={!draft.trim() || sending}
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-zinc-500">
          Want to track your existing applications or manage leave?{" "}
          <Link href="/signin" className="font-semibold text-blue-600 hover:underline">
            Sign in to your portal
          </Link>
        </p>
      </main>
    </div>
  );
}
