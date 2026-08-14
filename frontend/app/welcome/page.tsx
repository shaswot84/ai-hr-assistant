"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

interface ChatBubble {
  id: string;
  role: "assistant" | "user";
  text: string;
}

const GREETING =
  "Hi! I can answer questions about company policy and open roles. Ask me anything, or sign in to apply, check an application, or manage leave.";

//: Chat isn't wired to the real assistant yet (that's landing separately) —
//: this keeps the shell honest about that instead of pretending to answer.
const STUB_REPLY =
  "I'm not connected to live answers yet — that's landing soon. In the meantime, sign in to apply or check status, or browse open roles below.";

/** Logged-out homepage: the one-way destination after the login splash's
 * lamp is pulled. Chat is a UI shell for now (see STUB_REPLY) — the real
 * RBAC-aware assistant wiring is separate, in-progress work. */
export default function WelcomePage() {
  const [mounted, setMounted] = useState(false);
  const [messages, setMessages] = useState<ChatBubble[]>([
    { id: "greeting", role: "assistant", text: GREETING },
  ]);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // triggers the CSS transition below on the frame after mount, so the
    // page visibly settles in rather than snapping into place after the
    // login page's ignite wash
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-u`, role: "user", text },
      { id: `${Date.now()}-a`, role: "assistant", text: STUB_REPLY },
    ]);
    setDraft("");
  }

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
              <svg className="h-[18px] w-[18px] text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
              <p className="text-[11px] text-zinc-400">HR Platform</p>
            </div>
          </div>
          <Link href="/signin" className="btn-primary">
            Sign In
          </Link>
        </div>
      </header>

      <main
        className={`mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6 transition-all duration-500 ease-out sm:px-6 lg:py-10 ${
          mounted ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
        }`}
      >
        <div className="mb-5">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
            Ask about policy or open roles
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            No account needed to browse or ask questions — sign in only when you&apos;re ready to
            apply or manage your requests.
          </p>
        </div>

        <div className="card flex flex-1 flex-col overflow-hidden">
          <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-blue-600 text-white"
                      : "border border-zinc-200 bg-zinc-50 text-zinc-700"
                  }`}
                >
                  {m.text}
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-zinc-200 p-3">
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about policy, benefits, or open roles…"
              className="input flex-1"
            />
            <button type="submit" className="btn-primary" disabled={!draft.trim()}>
              Send
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-sm text-zinc-500">
          Prefer to browse directly?{" "}
          <Link href="/candidate" className="link">
            See open vacancies
          </Link>
        </p>
      </main>
    </div>
  );
}
