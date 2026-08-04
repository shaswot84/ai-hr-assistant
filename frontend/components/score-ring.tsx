"use client";

import { useEffect, useState } from "react";

export function ScoreRing({ score }: { score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    let raf: number;
    const duration = 800;
    const start = performance.now();

    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(eased * clamped));
      if (progress < 1) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [clamped]);

  const radius = 50;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (display / 100) * circumference;

  return (
    <div className="relative flex h-20 w-20 shrink-0 items-center justify-center">
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth="10"
        />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke="var(--foreground)"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-xl font-semibold tabular-nums">{display}</span>
        <span className="text-[10px] text-muted">/ 100</span>
      </div>
    </div>
  );
}