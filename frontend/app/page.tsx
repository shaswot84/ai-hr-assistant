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

// The cord is a physical rope (verlet simulation). It hangs from the lamp's
// attachment point (PIVOT); the bead (last point) is driven by the pointer
// while dragged and by a spring on release, and the whole rope sags, trails,
// and ripples naturally.
const PIVOT_X = 130; // attachment point under the shade (svg units)
const PIVOT_Y = 110;
const REST_X = 130; // bead rest position
const REST_Y = 190;
const REST_DIST = 80; // pivot → rest bead
const CORD_TRAVEL = 36; // how far down (svg units) the bead can be pulled
const CORD_THRESHOLD = 18; // min pull to ignite
const CORD_MAX_SWING_X = 44; // max sideways travel of the bead
// Rope physics. Zero slack + enough constraint passes = a taut, completely
// straight cord at rest (verified: sub-pixel deviation); it only ripples/
// trails while the bead moves, then settles straight again.
const ROPE_POINTS = 6; // simulation points (5 segments) — few, so it stays stiff/straight
const ROPE_GRAVITY = 800; // units/s² (kept for natural fall; slack=0 keeps it straight)
const ROPE_MAX_SLACK = 0; // no extra length — the rope is always taut/straight
const ROPE_DAMPING = 0.98; // verlet velocity damping
const ROPE_ITERATIONS = 16; // constraint relaxation passes per frame (converges straight)
// Sling spring: an underdamped harmonic oscillator (ω rad/s, ζ damping ratio).
// Released, the bead whips past rest in the OPPOSITE direction (up/against the
// pull) before settling — the natural cord behavior.
const SLING_OMEGA = 8;
const SLING_ZETA = 0.15;
const PHYSICS_DT = 1 / 60;
//: How long the ignite wash plays before navigating — must match the
//: transition-duration below so the redirect fires right as it completes.
const IGNITE_MS = 450;

interface Point {
  x: number;
  y: number;
}

/** Total rope length for a given pivot→bead distance: taut when pulled, a
 *  little slack (for droop) when at rest. */
function ropeLength(dist: number) {
  const f = Math.max(0, Math.min(1, (dist - REST_DIST) / CORD_TRAVEL));
  return dist + ROPE_MAX_SLACK * (1 - f);
}

/** One verlet step of the rope: integrate inner points under gravity, then
 *  relax segment lengths so the chain connects the pinned pivot to `target`.
 *  Mutates `points`/`prev` in place for performance. */
function stepRope(points: Point[], prev: Point[], target: Point) {
  const dist = Math.hypot(target.x - PIVOT_X, target.y - PIVOT_Y);
  const seg = ropeLength(dist) / (ROPE_POINTS - 1);

  for (let i = 1; i < ROPE_POINTS - 1; i++) {
    const vx = (points[i].x - prev[i].x) * ROPE_DAMPING;
    const vy = (points[i].y - prev[i].y) * ROPE_DAMPING;
    prev[i] = points[i];
    points[i] = {
      x: points[i].x + vx,
      y: points[i].y + vy + ROPE_GRAVITY * PHYSICS_DT * PHYSICS_DT,
    };
  }

  for (let iter = 0; iter < ROPE_ITERATIONS; iter++) {
    for (let i = 0; i < ROPE_POINTS - 1; i++) {
      const dx = points[i + 1].x - points[i].x;
      const dy = points[i + 1].y - points[i].y;
      const d = Math.hypot(dx, dy) || 1e-6;
      const diff = (d - seg) / d;
      if (i === 0) {
        points[i + 1] = { x: points[i + 1].x - dx * diff, y: points[i + 1].y - dy * diff };
      } else if (i === ROPE_POINTS - 2) {
        points[i] = { x: points[i].x + dx * diff, y: points[i].y + dy * diff };
      } else {
        points[i] = { x: points[i].x + dx * diff * 0.5, y: points[i].y + dy * diff * 0.5 };
        points[i + 1] = { x: points[i + 1].x - dx * diff * 0.5, y: points[i + 1].y - dy * diff * 0.5 };
      }
    }
    points[0] = { x: PIVOT_X, y: PIVOT_Y };
    points[ROPE_POINTS - 1] = target;
  }
  return points;
}

/** The settled resting shape of the rope — a gentle droop — computed once. */
function computeRestRope() {
  const points: Point[] = [];
  for (let i = 0; i < ROPE_POINTS; i++) {
    points.push({ x: PIVOT_X, y: PIVOT_Y + (REST_Y - PIVOT_Y) * (i / (ROPE_POINTS - 1)) });
  }
  const prev = points.map((p) => ({ ...p }));
  for (let f = 0; f < 400; f++) stepRope(points, prev, { x: REST_X, y: REST_Y });
  return points;
}
const REST_ROPE = computeRestRope();

/** Smooth open curve through the rope points (midpoint quadratic B-spline). */
function ropePath(points: Point[]) {
  if (points.length < 2) return "";
  let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  for (let i = 1; i < points.length - 1; i++) {
    const mx = (points[i].x + points[i + 1].x) / 2;
    const my = (points[i].y + points[i + 1].y) / 2;
    d += ` Q ${points[i].x.toFixed(1)} ${points[i].y.toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`;
  }
  const last = points[points.length - 1];
  d += ` L ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
  return d;
}

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

/** Desk lamp SVG: the pull cord is a physical rope — draggable, and igniting
 *  the transition to /welcome when pulled. */
function Lamp({ on, dragging, slinging, rope, bead, svgRef, handlers }: LampProps) {
  const shadeFill = on ? "#ffffff" : "#f5f0e6";
  const driving = dragging || slinging;
  return (
    <div className="relative flex h-[340px] w-[220px] items-start justify-center sm:h-[430px] sm:w-[280px]">
      <svg ref={svgRef} className="h-full w-full overflow-visible" viewBox="0 0 200 300" xmlns="http://www.w3.org/2000/svg">
        {/* glow tints neutral grey, not the lamp's usual warm gold — it's
            the same hand-off color as the full-screen ignite wash below, so
            the bulb and the transition read as one continuous flash */}
        <ellipse
          className={`transition-opacity duration-500 ${on ? "opacity-60" : "opacity-0"}`}
          cx="100"
          cy="110"
          rx="60"
          ry="30"
          fill="#a1a1aa"
          style={{ filter: "blur(15px)" }}
        />

        <rect className="transition-colors duration-500" x="92" y="100" width="16" height="160" rx="8" fill="#d1ccc2" />
        <rect className="transition-colors duration-500" x="60" y="250" width="80" height="12" rx="6" fill="#d1ccc2" />

        {/* The rope is drawn point-to-point from the lamp's attachment point
            (PIVOT) down to the bead, sagging under gravity — so it reads as a
            real thread and can never detach. Idle, the group sways around the
            pivot (cord-sway keyframes); while dragged/slung the rope is driven
            by the physics loop (same element, so pointer capture survives). */}
        <g
          className={`cursor-grab touch-none select-none outline-none active:cursor-grabbing ${
            driving ? "" : "cord-sway"
          }`}
          onPointerDown={handlers.onDown}
          onPointerMove={handlers.onMove}
          onPointerUp={handlers.onUp}
          onPointerCancel={handlers.onUp}
          onKeyDown={handlers.onKey}
          tabIndex={0}
          role="button"
          aria-label="Pull the lamp cord to enter the app"
        >
          <path
            d={ropePath(rope)}
            fill="none"
            stroke="#555"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <circle cx={bead.x} cy={bead.y} r="6" fill="#d4a373" />
          <circle cx={bead.x} cy={bead.y} r="26" fill="transparent" pointerEvents="all" />
        </g>

        <path
          className={`transition-all duration-500 ${on ? "drop-shadow-[0_0_30px_rgba(161,161,170,0.5)]" : ""}`}
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
  slinging: boolean;
  rope: Point[];
  bead: Point;
  svgRef: React.RefObject<SVGSVGElement | null>;
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
  const [slinging, setSlinging] = useState(false);
  const [rope, setRope] = useState<Point[]>(() => REST_ROPE.map((p) => ({ ...p })));
  const [bead, setBead] = useState<Point>({ x: REST_X, y: REST_Y });
  const ropeRef = useRef<Point[]>(REST_ROPE.map((p) => ({ ...p })));
  const prevRef = useRef<Point[]>(REST_ROPE.map((p) => ({ ...p })));
  // Bead spring: displacement from rest while released (integrated); while
  // dragged it is locked to the pointer target.
  const springRef = useRef({ dx: 0, dy: 0, vx: 0, vy: 0 });
  const dragTargetRef = useRef<Point>({ x: REST_X, y: REST_Y });
  const draggingRef = useRef(false);
  const slingRafRef = useRef<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // Cancel the sling loop if the page unmounts mid-whiplash.
  useEffect(() => {
    return () => {
      if (slingRafRef.current !== null) cancelAnimationFrame(slingRafRef.current);
    };
  }, []);

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

  /** Map a pointer client position to SVG viewBox coordinates (200×300). */
  function clientToSvg(clientX: number, clientY: number) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return { x: REST_X, y: REST_Y };
    return {
      x: ((clientX - rect.left) / rect.width) * 200,
      y: ((clientY - rect.top) / rect.height) * 300,
    };
  }

  /** Keep the bead in a natural reachable region: it can be pulled down
   *  (but never above rest) and swung sideways, never leaving the lamp. */
  function clampBead(x: number, y: number) {
    return {
      x: Math.max(PIVOT_X - CORD_MAX_SWING_X, Math.min(PIVOT_X + CORD_MAX_SWING_X, x)),
      y: Math.max(REST_Y, Math.min(REST_Y + CORD_TRAVEL, y)),
    };
  }

  /** Run the combined spring + rope physics loop. While dragging the spring is
   *  locked to the pointer target; on release it becomes an underdamped
   *  oscillator, whipping the bead PAST rest in the opposite direction of the
   *  pull while the rope ripples behind it. Stops once everything calms. */
  function startRopeLoop() {
    if (slingRafRef.current !== null) cancelAnimationFrame(slingRafRef.current);
    setSlinging(true);

    const step = () => {
      const s = springRef.current;
      if (draggingRef.current) {
        const t = dragTargetRef.current;
        s.dx = t.x - REST_X;
        s.dy = t.y - REST_Y;
        s.vx = 0;
        s.vy = 0;
      } else {
        const ax = -SLING_OMEGA * SLING_OMEGA * s.dx - 2 * SLING_ZETA * SLING_OMEGA * s.vx;
        const ay = -SLING_OMEGA * SLING_OMEGA * s.dy - 2 * SLING_ZETA * SLING_OMEGA * s.vy;
        s.vx += ax * PHYSICS_DT;
        s.dx += s.vx * PHYSICS_DT;
        s.vy += ay * PHYSICS_DT;
        s.dy += s.vy * PHYSICS_DT;
      }

      const target: Point = { x: REST_X + s.dx, y: REST_Y + s.dy };
      stepRope(ropeRef.current, prevRef.current, target);
      setRope(ropeRef.current.map((p) => ({ ...p })));
      setBead({ x: target.x, y: target.y });

      // Settle: spring near rest AND the rope no longer moving.
      if (
        !draggingRef.current &&
        Math.abs(s.dx) < 0.3 &&
        Math.abs(s.dy) < 0.3 &&
        Math.abs(s.vx) < 1 &&
        Math.abs(s.vy) < 1
      ) {
        let calm = true;
        for (let i = 1; i < ROPE_POINTS - 1; i++) {
          const vx = ropeRef.current[i].x - prevRef.current[i].x;
          const vy = ropeRef.current[i].y - prevRef.current[i].y;
          if (Math.abs(vx) > 0.15 || Math.abs(vy) > 0.15) {
            calm = false;
            break;
          }
        }
        if (calm) {
          setSlinging(false);
          return;
        }
      }
      slingRafRef.current = requestAnimationFrame(step);
    };
    slingRafRef.current = requestAnimationFrame(step);
  }

  function handleCordDown(e: React.PointerEvent<SVGGElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    draggingRef.current = true;
    setDragging(true);
    const p = clientToSvg(e.clientX, e.clientY);
    dragTargetRef.current = clampBead(p.x, p.y);
    startRopeLoop();
  }

  function handleCordMove(e: React.PointerEvent<SVGGElement>) {
    if (!draggingRef.current) return;
    const p = clientToSvg(e.clientX, e.clientY);
    dragTargetRef.current = clampBead(p.x, p.y);
  }

  function handleCordUp() {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    setDragging(false);
    const t = dragTargetRef.current;
    // A full pull ignites the transition; the spring (already at the pull
    // position, zero velocity) takes over and slings the cord back naturally.
    if (t.y - REST_Y > CORD_THRESHOLD) ignite();
  }

  function handleCordKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      ignite();
      draggingRef.current = false;
      setDragging(false);
      springRef.current = { dx: 0, dy: CORD_TRAVEL, vx: 0, vy: 0 };
      startRopeLoop();
    }
  }

  if (checkingSession) {
    return <div className="min-h-screen bg-[#0a0a0a]" />;
  }

  return (
    <div
      className={`relative min-h-screen select-none overflow-hidden transition-colors duration-500 ${
        igniting ? "bg-white" : "bg-[#0a0a0a]"
      }`}
    >
      {/* neutral grey glow that blooms to fill the screen on ignite,
          washing the page to white right as we hand off to the (light-themed)
          app — grey rather than a lamp's usual warm gold, sitting midway
          between the dark splash and the light app's own palettes */}
      <div
        className={`pointer-events-none fixed inset-0 origin-center bg-[radial-gradient(circle_at_50%_38%,rgba(161,161,170,0.9),rgba(255,255,255,0.5)_60%,rgba(255,255,255,0)_100%)] transition-all ease-in ${
          igniting ? "scale-[6] opacity-100 duration-500" : "scale-100 opacity-0 duration-500"
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
          <p className="mt-9 text-xs text-zinc-500">
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
            slinging={slinging}
            rope={rope}
            bead={bead}
            svgRef={svgRef}
            handlers={{
              onDown: handleCordDown,
              onMove: handleCordMove,
              onUp: handleCordUp,
              onKey: handleCordKey,
            }}
          />

          <p className="animate-pulse text-center text-sm text-white/50">
            Pull the cord to get started
          </p>
        </div>
      </div>
    </div>
  );
}
