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
              <div><span className="font-medium text-zinc-800">Type:</span> {c.document_type || "—"}</div>
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
  const inputRef = useRef<HTMLInputElement>(null);

  // Web Speech API Voice Input
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(true);
  const [speechInterim, setSpeechInterim] = useState("");
  const [speechError, setSpeechError] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const hasSpeech =
        "SpeechRecognition" in window || "webkitSpeechRecognition" in window;
      setSpeechSupported(Boolean(hasSpeech));
    }
  }, []);

  const stopListening = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // ignore
      }
    }
    setIsListening(false);
    setSpeechInterim("");
  };

  const startListening = () => {
    if (typeof window === "undefined" || sending) return;
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setSpeechError("Speech recognition is not supported in this browser.");
      return;
    }

    try {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {
          // ignore
        }
      }

      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = typeof navigator !== "undefined" ? navigator.language || "en-US" : "en-US";

      recognition.onstart = () => {
        setIsListening(true);
        setSpeechInterim("");
        setSpeechError(null);
      };

      recognition.onresult = (event: any) => {
        let interim = "";
        let finalTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcript = event.results[i][0]?.transcript || "";
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interim += transcript;
          }
        }

        if (interim) {
          setSpeechInterim(interim);
        }

        if (finalTranscript) {
          setDraft((prev) => {
            const trimmed = prev.trim();
            const separator = trimmed.length > 0 ? " " : "";
            return trimmed + separator + finalTranscript.trim();
          });
          setSpeechInterim("");
          if (inputRef.current) {
            inputRef.current.focus();
          }
        }
      };

      recognition.onerror = (event: any) => {
        setIsListening(false);
        setSpeechInterim("");
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          setSpeechError("Microphone access was denied. Please check your browser permissions.");
        } else if (event.error === "network") {
          setSpeechError("Speech recognition network error. Please check your connection.");
        }
      };

      recognition.onend = () => {
        setIsListening(false);
        setSpeechInterim("");
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch {
      setIsListening(false);
      setSpeechInterim("");
      setSpeechError("Failed to start voice recognition.");
    }
  };

  const toggleVoiceInput = () => {
    if (isListening) stopListening();
    else startListening();
  };

  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.abort();
        } catch {
          // ignore
        }
      }
    };
  }, []);

  useEffect(() => {
    if (sending && isListening) {
      stopListening();
    }
  }, [sending, isListening]);

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

          {isListening && (
            <div className="flex items-center justify-between gap-2 px-3.5 py-2 mx-4 mt-2 bg-rose-50 border border-rose-200/90 rounded-xl text-rose-700 text-xs shadow-2xs animate-fade-in">
              <div className="flex items-center gap-2.5 min-w-0">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-600"></span>
                </span>
                <span className="font-semibold text-rose-900 shrink-0">Listening…</span>
                {speechInterim ? (
                  <span className="italic text-zinc-800 font-medium truncate">&ldquo;{speechInterim}&rdquo;</span>
                ) : (
                  <span className="text-rose-600/80 truncate">Speak into your microphone…</span>
                )}
              </div>
              <button
                type="button"
                onClick={stopListening}
                className="shrink-0 text-[11px] font-semibold text-rose-700 hover:text-rose-900 bg-rose-100/90 hover:bg-rose-200 px-2 py-0.5 rounded-md transition-colors"
              >
                Done
              </button>
            </div>
          )}

          {speechError && (
            <div className="mx-4 mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 flex items-center justify-between">
              <span>{speechError}</span>
              <button
                type="button"
                onClick={() => setSpeechError(null)}
                className="text-red-500 hover:text-red-800 ml-2 font-bold"
              >
                ×
              </button>
            </div>
          )}

          <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-zinc-200 bg-zinc-50/70 p-3 sm:p-4">
            <input
              ref={inputRef}
              type="text"
              value={draft}
              disabled={sending}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about policy, vacancies, or how to apply…"
              className="input flex-1 bg-white"
            />
            {/* Voice Input Button */}
            <button
              type="button"
              onClick={toggleVoiceInput}
              disabled={sending || !speechSupported}
              className={`inline-flex items-center justify-center h-10 w-10 rounded-xl transition-all shrink-0 ${
                isListening
                  ? "bg-rose-600 hover:bg-rose-700 text-white shadow-md ring-4 ring-rose-200/80 animate-pulse"
                  : "border border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900 hover:border-zinc-300 active:scale-95 shadow-2xs"
              } ${!speechSupported ? "opacity-40 cursor-not-allowed" : ""}`}
              title={
                !speechSupported
                  ? "Voice input not supported in this browser"
                  : isListening
                  ? "Listening... Click to stop"
                  : "Voice input (Speak to Type)"
              }
              aria-label={isListening ? "Stop voice input" : "Start voice input"}
            >
              {isListening ? (
                <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
                  <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
                  />
                </svg>
              )}
            </button>
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
