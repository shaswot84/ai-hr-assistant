/** A small circular 0-100 score indicator (AI evaluation headline score). */
export function ScoreRing({ score, label }: { score: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, score));
  const size = 76;
  const radius = 32;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const color = clamped >= 70 ? "#059669" : clamped >= 40 ? "#d97706" : "#dc2626";

  return (
    <div className="flex items-center gap-4">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#e4e4e7" strokeWidth="6" />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-semibold tabular-nums text-zinc-900">{clamped}</span>
        </div>
      </div>
      {label && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">{label}</p>
          <p className="mt-0.5 text-[11px] text-zinc-400">out of 100</p>
        </div>
      )}
    </div>
  );
}
