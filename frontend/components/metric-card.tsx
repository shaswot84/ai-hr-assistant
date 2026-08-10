/**
 * Compact metric summary tile (PostHog-style): small label, a large
 * tabular-numeral value, an optional trend delta, and a quiet icon chip.
 * No shadows, no gradient — signal over decoration.
 */
export function MetricCard({
  label,
  value,
  sub,
  delta,
  icon,
  iconClass = "bg-zinc-100 text-zinc-500",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  /** e.g. { value: "+18%", direction: "up" | "down" | "neutral" } */
  delta?: { value: string; direction: "up" | "down" | "neutral" };
  icon?: React.ReactNode;
  iconClass?: string;
}) {
  const deltaColor =
    delta?.direction === "up"
      ? "text-emerald-600"
      : delta?.direction === "down"
        ? "text-red-600"
        : "text-zinc-500";

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-medium text-zinc-500">{label}</p>
        {icon && (
          <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${iconClass}`}>
            {icon}
          </div>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-[26px] font-semibold leading-none tracking-tight tabular-nums text-zinc-900">
          {value}
        </span>
        {delta && (
          <span className={`text-[13px] font-medium tabular-nums ${deltaColor}`}>
            {delta.value}
          </span>
        )}
      </div>
      {sub && <p className="mt-1.5 text-xs text-zinc-400">{sub}</p>}
    </div>
  );
}
