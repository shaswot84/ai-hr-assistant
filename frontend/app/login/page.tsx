"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { setAuthToken } from "@/lib/auth";
import { useToast } from "@/components/toast";

const ROLE_HOME: Record<string, string> = {
  HR_ADMIN: "/manager",
  CANDIDATE: "/candidate",
  EMPLOYEE: "/employee",
};

const DEMOS: Record<string, { email: string; password: string }> = {
  manager: { email: "manager@example.com", password: "manager123" },
  employee: { email: "employee@example.com", password: "employee123" },
  candidate: { email: "candidate@example.com", password: "candidate123" },
};

const DEMO_LABELS: Record<string, string> = {
  manager: "Manager",
  employee: "Employee",
  candidate: "Candidate",
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

/** Desk lamp SVG: the pull cord is draggable and toggles the lamp + form. */
function Lamp({ on, dragging, cordY, handlers }: LampProps) {
  const shadeFill = on ? "#ffffff" : "#f5f0e6";
  return (
    <div className="relative flex h-[340px] w-[220px] items-start justify-center sm:h-[430px] sm:w-[280px]">
      <svg className="h-full w-full overflow-visible" viewBox="0 0 200 300" xmlns="http://www.w3.org/2000/svg">
        <ellipse
          className={`transition-opacity duration-500 ${on ? "opacity-60" : "opacity-0"}`}
          cx="100"
          cy="110"
          rx="60"
          ry="30"
          fill="#ffdb8a"
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
          aria-pressed={on}
          aria-label="Pull the lamp cord to reveal the sign-in form"
        >
          <line className="cord-line" x1="130" y1="110" x2="130" y2="180" stroke="#555" strokeWidth="2" />
          <circle className="cord-bead" cx="130" cy="190" r="6" fill="#d4a373" />
          <circle className="cord-hit" cx="130" cy="190" r="26" fill="transparent" pointerEvents="all" />
        </g>

        <path
          className={`transition-all duration-500 ${on ? "drop-shadow-[0_0_30px_rgba(255,255,200,0.4)]" : ""}`}
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

export default function LoginPage() {
  const router = useRouter();
  const { addToast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [on, setOn] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [cordY, setCordY] = useState(0);
  const cordYRef = useRef(0);
  const dragStartRef = useRef<number | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (on) emailRef.current?.focus();
  }, [on]);

  function toggleLamp() {
    playClick();
    setOn((v) => !v);
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
    if (cordYRef.current > CORD_THRESHOLD) toggleLamp();
    dragStartRef.current = null;
    cordYRef.current = 0;
    setDragging(false);
    setCordY(0);
  }

  function handleCordKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleLamp();
    }
  }

  function fillDemo(role: keyof typeof DEMOS) {
    setEmail(DEMOS[role].email);
    setPassword(DEMOS[role].password);
    setSelectedDemo(role);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.login(email, password);
      setAuthToken(res.access_token);
      addToast(`Logged in successfully as ${res.user.display_name}.`, "success");
      router.push(ROLE_HOME[res.user.coarse_role] ?? "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not sign in. Is the backend running?");
      setSubmitting(false);
    }
  }

  const inputCls =
    "w-full rounded-[14px] border border-white/10 bg-white/[0.07] px-4 py-3.5 text-white placeholder-white/30 outline-none transition focus:border-[#d4a373] focus:bg-white/[0.12]";

  return (
    <div
      className={`relative min-h-screen select-none overflow-x-hidden transition-colors duration-500 ${
        on ? "bg-[#1c1f24]" : "bg-[#121417]"
      }`}
    >
      {/* warm glow once the lamp is on */}
      <div
        className={`pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_50%_40%,rgba(255,214,110,0.3),transparent_70%)] transition-opacity duration-500 ${
          on ? "opacity-100" : "opacity-0"
        }`}
      />

      {/* brand */}
      <div className="absolute left-6 top-6 z-10 flex items-center gap-2.5">
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
        {/* ── Left half: project details ⇄ sign-in form ─────────────── */}
        <div className="order-2 grid items-center lg:order-1">
          {/* details — visible while the lamp is off */}
          <div
            className={`col-start-1 row-start-1 max-w-md justify-self-center transition-all duration-500 ease-out ${
              on ? "pointer-events-none -translate-x-10 opacity-0" : "translate-x-0 opacity-100"
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

          {/* sign-in form — springs in when the lamp is switched on */}
          <div
            className={`col-start-1 row-start-1 w-full max-w-md justify-self-center transition-all duration-700 ease-[cubic-bezier(0.175,0.885,0.32,1.275)] ${
              on ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-12 opacity-0"
            }`}
          >
            <div className="rounded-[20px] border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl sm:p-10">
              <h2 className="text-center text-xl font-semibold text-white">Welcome</h2>
              <p className="mt-1 text-center text-sm text-white/40">
                Sign in to continue to your HR workspace.
              </p>

              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                <div>
                  <label className="mb-2 ml-1 block text-[13px] text-white/60" htmlFor="login-email">
                    Email address
                  </label>
                  <input
                    id="login-email"
                    ref={emailRef}
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputCls}
                    placeholder="you@example.com"
                  />
                </div>

                <div>
                  <label className="mb-2 ml-1 block text-[13px] text-white/60" htmlFor="login-password">
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="login-password"
                      type={showPassword ? "text" : "password"}
                      required
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className={`${inputCls} pr-11`}
                      placeholder="••••••••"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((s) => !s)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-white/40 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#d4a373]/50"
                    >
                      {showPassword ? (
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={1.75}
                            d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                          />
                        </svg>
                      ) : (
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={1.75}
                            d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                          />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>

                {error && (
                  <p
                    className="flex items-start gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-sm text-red-200"
                    role="alert"
                  >
                    <svg className="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting}
                  className="flex w-full items-center justify-center gap-2 rounded-[14px] bg-[linear-gradient(135deg,#bf953f,#fcf6ba,#b38728,#fcf6ba,#aa771c)] py-3.5 text-[15px] font-semibold text-[#121417] transition hover:scale-[1.02] hover:brightness-110 disabled:opacity-60 disabled:hover:scale-100"
                >
                  {submitting ? (
                    <>
                      <span
                        aria-hidden="true"
                        className="h-4 w-4 animate-spin rounded-full border-2 border-[#121417]/30 border-t-[#121417]"
                      />
                      Signing in…
                    </>
                  ) : (
                    "Sign In"
                  )}
                </button>
              </form>

              <div className="mt-7">
                <div className="flex items-center gap-3">
                  <span className="h-px flex-1 bg-white/10" />
                  <span className="text-[11px] font-medium uppercase tracking-wider text-white/40">
                    or use a demo account
                  </span>
                  <span className="h-px flex-1 bg-white/10" />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2">
                  {(Object.keys(DEMOS) as Array<keyof typeof DEMOS>).map((role) => {
                    const active = selectedDemo === role;
                    const baseCls =
                      "flex items-center justify-center gap-1.5 rounded-xl border px-2 py-2 text-xs font-medium transition";
                    // Candidates enter through the public careers page — no
                    // sign-in needed to browse or apply for the first time.
                    if (role === "candidate") {
                      return (
                        <Link
                          key={role}
                          href="/candidate"
                          className={`${baseCls} border-white/10 bg-white/5 text-white/70 hover:border-[#d4a373]/50 hover:text-white`}
                        >
                          {DEMO_LABELS[role]}
                        </Link>
                      );
                    }
                    return (
                      <button
                        key={role}
                        type="button"
                        onClick={() => fillDemo(role)}
                        aria-pressed={active}
                        className={`${baseCls} ${
                          active
                            ? "border-[#d4a373] bg-[#d4a373]/10 text-[#f5c76a]"
                            : "border-white/10 bg-white/5 text-white/70 hover:border-[#d4a373]/50 hover:text-white"
                        }`}
                      >
                        {active && (
                          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                        {DEMO_LABELS[role]}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-2.5 text-center text-xs text-white/30">
                  Manager / Employee demos are filled automatically — just press Sign In. Candidates
                  can browse vacancies without signing in.
                </p>
                <p className="mt-1.5 text-center text-[11px] text-white/25">
                  Returning candidate? Sign in with {DEMOS.candidate.email} / {DEMOS.candidate.password}
                  to track your applications.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* ── Right half: the lamp ─────────────────────────────────── */}
        <div className="order-1 flex flex-col items-center gap-6 lg:order-2">
          <Lamp
            on={on}
            dragging={dragging}
            cordY={cordY}
            handlers={{
              onDown: handleCordDown,
              onMove: handleCordMove,
              onUp: handleCordUp,
              onKey: handleCordKey,
            }}
          />

          <p
            className={`text-center text-sm transition-opacity duration-500 ${
              on ? "text-white/30" : "animate-pulse text-white/40"
            }`}
          >
            {on ? "Pull the cord again to switch it off" : "Pull the cord to switch on the form"}
          </p>
        </div>
      </div>
    </div>
  );
}
