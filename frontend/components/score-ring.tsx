/** A small circular 0-100 score indicator (AI evaluation headline score). */
export function ScoreRing({ score, label }: { score: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const color = clamped >= 70 ? "#059669" : clamped >= 40 ? "#d97706" : "#dc2626";

  return (
    <div className="flex items-center gap-3">
      <svg width="64" height="64" viewBox="0 0 64 64" className="-rotate-90">
        <circle cx="32" cy="32" r={radius} fill="none" stroke="#e5e5e5" strokeWidth="6" />
        <circle
          cx="32"
          cy="32"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="-ml-16 flex w-16 flex-col items-center justify-center">
        <span className="text-lg font-semibold">{clamped}</span>
      </div>
      {label && <span className="ml-2 text-sm text-muted">{label}</span>}
    </div>
  );
}
