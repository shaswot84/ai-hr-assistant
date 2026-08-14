"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

const FEATURES = [
  {
    title: "Policy Q&A, grounded in your docs",
    desc: "Ask anything about HR policy — every answer cites the source documents.",
    icon: (
      <svg className="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.75}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>
    ),
  },
  {
    title: "AI resume screening",
    desc: "Requirements checks, strengths and gaps for every application — in seconds.",
    icon: (
      <svg className="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.75}
          d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
        />
      </svg>
    ),
  },
  {
    title: "One calm workspace for HR",
    desc: "Recruitment, leave and knowledge in a single, focused dashboard.",
    icon: (
      <svg className="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.75}
          d="M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z"
        />
      </svg>
    ),
  },
];

const CORD_TRAVEL = 60;
const CORD_THRESHOLD = 30;
//: How long the ignite wash plays before navigating — must match the
//: transition-duration below so the redirect fires right as it completes.
const IGNITE_MS = 750;

/** Tiny synthesized "click" for the cord pull — no external audio asset. */
function playClick() {
  try {
    const Ctx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.value = 850;
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.08);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.09);
    osc.onended = () => ctx.close();
  } catch {
    /* audio unavailable — ignore */
  }
}

/** Desk lamp SVG: the pull cord is draggable and ignites the transition to /welcome. */
function Lamp({ on, dragging, cordY, handlers }: LampProps) {
  const shadeFill = on ? "#ffffff" : "#f5f0e6";
  return (
    <div className="relative flex h-[340px] w-[220px] items-start justify-center sm:h-[430px] sm:w-[280px]">
      <svg className="h-full w-full overflow-visible" viewBox="0 0 200 300" xmlns="http://www.w3.org/2000/svg">
        {/* glow tints blue, not the lamp's usual warm gold — it's the same
            hand-off color as the full-screen ignite wash below, so the bulb
            and the transition read as one continuous flash */}
        <ellipse
          className={`transition-opacity duration-500 ${on ? "opacity-60" : "opacity-0"}`}
          cx="100"
          cy="110"
          rx="60"
          ry="30"
          fill="#60a5fa"
          style={{ filter: "blur(15px)" }}
        />

        <rect className="transition-colors duration-500" x="92" y="100" width="16" height="160" rx="8" fill="#d1ccc2" />
        <rect className="transition-colors duration-500" x="60" y="250" width="80" height="12" rx="6" fill="#d1ccc2" />

        <g
          className={`cursor-grab touch-none select-none outline-none ${
            dragging
              ? ""
              : "transition-transform duration-500 ease-[cubic-bezier(0.68,-0.55,0.265,1.55)]"
          } active:cursor-grabbing`}
          style={{ transform: `translateY(${cordY}px)` }}
          onPointerDown={handlers.onDown}
          onPointerMove={handlers.onMove}
          onPointerUp={handlers.onUp}
          onPointerCancel={handlers.onUp}
          onKeyDown={handlers.onKey}
          tabIndex={0}
          role="button"
          aria-label="Pull the lamp cord to enter the app"
        >
          <line className="cord-line" x1="130" y1="110" x2="130" y2="180" stroke="#555" strokeWidth="2" />
          <circle className="cord-bead" cx="130" cy="190" r="6" fill="#d4a373" />
          <circle className="cord-hit" cx="130" cy="190" r="26" fill="transparent" pointerEvents="all" />
        </g>

        <path
          className={`transition-all duration-500 ${on ? "drop-shadow-[0_0_30px_rgba(96,165,250,0.5)]" : ""}`}
          d="M30 110 C 30 50, 170 50, 170 110 C 170 125, 30 125, 30 110 Z"
          fill={shadeFill}
        />
      </svg>
    </div>
  );
}

interface LampProps {
  on: boolean;
  dragging: boolean;
  cordY: number;
  handlers: {
    onDown: (e: React.PointerEvent<SVGGElement>) => void;
    onMove: (e: React.PointerEvent<SVGGElement>) => void;
    onUp: () => void;
    onKey: (e: React.KeyboardEvent) => void;
  };
}

export default function HomePage() {
  const router = useRouter();

  // Already-authenticated visitors who land here get sent straight to their
  // portal instead of having to pull the cord again; a stale/invalid token
  // skips the splash entirely and goes straight to reauth. `checkingSession`
  // only ever matters for the token-present case — both outcomes below
  // navigate away, so a genuinely unauthenticated visitor (the common case)
  // sees the splash instantly with no async gate at all.
  const [checkingSession, setCheckingSession] = useState(true);

  const [igniting, setIgniting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [cordY, setCordY] = useState(0);
  const cordYRef = useRef(0);
  const dragStartRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const token = getAuthToken();
    if (!token) {
      // Nothing to verify — resolve on a microtask so this stays a reaction
      // to an external check rather than a synchronous effect-body setState.
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
        if (!cancelled) router.replace(ROLE_HOME[res.user.coarse_role] ?? "/welcome");
      })
      .catch(() => {
        if (!cancelled) router.replace("/signin");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  /** Pulling the cord switches the lamp on for good — no toggling back off,
   * this page is a one-way splash into the app. The lamp itself is never
   * seen again after this. */
  function ignite() {
    if (igniting) return;
    playClick();
    setIgniting(true);
    setTimeout(() => router.push("/welcome"), IGNITE_MS);
  }

  function handleCordDown(e: React.PointerEvent<SVGGElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragStartRef.current = e.clientY;
    setDragging(true);
  }

  function handleCordMove(e: React.PointerEvent<SVGGElement>) {
    if (dragStartRef.current === null) return;
    const y = Math.max(0, Math.min(CORD_TRAVEL, e.clientY - dragStartRef.current));
    cordYRef.current = y;
    setCordY(y);
  }

  function handleCordUp() {
    if (dragStartRef.current === null) return;
    if (cordYRef.current > CORD_THRESHOLD) ignite();
    dragStartRef.current = null;
    cordYRef.current = 0;
    setDragging(false);
    setCordY(0);
  }

  function handleCordKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      ignite();
    }
  }

  if (checkingSession) {
    return <div className="min-h-screen bg-[#121417]" />;
  }

  return (
    <div
      className={`relative min-h-screen select-none overflow-hidden transition-colors ${
        igniting ? "duration-700" : "duration-500"
      } ${igniting ? "bg-white" : "bg-[#121417]"}`}
    >
      {/* blue glow that blooms to fill the screen on ignite, washing the
          page to white right as we hand off to the (light-themed) app —
          blue rather than a lamp's usual warm gold, since it's the one
          accent color both the dark splash and the light app already share
          (the brand logo badge, the app's primary buttons/links) */}
      <div
        className={`pointer-events-none fixed inset-0 origin-center bg-[radial-gradient(circle_at_50%_38%,rgba(96,165,250,0.9),rgba(255,255,255,0.5)_60%,rgba(255,255,255,0)_100%)] transition-all ease-in ${
          igniting ? "scale-[6] opacity-100 duration-700" : "scale-100 opacity-0 duration-500"
        }`}
      />

      {/* brand */}
      <div
        className={`absolute left-6 top-6 z-10 flex items-center gap-2.5 transition-opacity duration-300 ${
          igniting ? "opacity-0" : "opacity-100"
        }`}
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 shadow-sm">
          <svg className="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
            />
          </svg>
        </div>
        <div className="leading-tight">
          <p className="text-[15px] font-semibold tracking-tight text-white">AI HR Assistant</p>
          <p className="text-xs text-zinc-500">HR Platform</p>
        </div>
      </div>

      <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-5xl flex-col px-6 py-24 lg:grid lg:grid-cols-2 lg:items-center lg:gap-14 lg:py-0">
        {/* ── Left half: project details ─────────────────────────────── */}
        <div
          className={`order-2 max-w-md justify-self-center transition-all duration-500 ease-out lg:order-1 ${
            igniting ? "-translate-x-10 opacity-0" : "translate-x-0 opacity-100"
          }`}
        >
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white sm:text-[34px]">
            Your AI-powered HR team, on autopilot.
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed text-zinc-400">
            Policy answers with real citations, AI resume screening, and recruitment
            workflows — in one calm workspace.
          </p>
          <ul className="mt-9 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex items-start gap-3.5">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-800 bg-zinc-900 text-blue-400">
                  {f.icon}
                </span>
                <div>
                  <p className="text-sm font-medium text-zinc-100">{f.title}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-zinc-500">{f.desc}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-9 text-xs text-zinc-600">
            Runs locally · PostgreSQL + pgvector · local model serving
          </p>
        </div>

        {/* ── Right half: the lamp ─────────────────────────────────── */}
        <div
          className={`order-1 flex flex-col items-center gap-6 transition-opacity duration-500 lg:order-2 ${
            igniting ? "opacity-0" : "opacity-100"
          }`}
        >
          <Lamp
            on={igniting}
            dragging={dragging}
            cordY={cordY}
            handlers={{
              onDown: handleCordDown,
              onMove: handleCordMove,
              onUp: handleCordUp,
              onKey: handleCordKey,
            }}
          />

          <p className="animate-pulse text-center text-sm text-white/40">
            Pull the cord to get started
          </p>
        </div>
      </div>
    </div>
  );
}
