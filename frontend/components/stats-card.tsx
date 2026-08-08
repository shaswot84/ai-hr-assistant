import { MetricCard } from "@/components/metric-card";

const COLORS = {
  blue: { icon: "bg-blue-50 text-blue-600" },
  green: { icon: "bg-emerald-50 text-emerald-600" },
  amber: { icon: "bg-amber-50 text-amber-600" },
  purple: { icon: "bg-violet-50 text-violet-600" },
} as const;

/**
 * Dashboard summary tile — kept as a thin wrapper over MetricCard so any
 * existing callers keep working with the same API (title/value/subtitle/icon).
 */
export function StatsCard({
  title,
  value,
  subtitle,
  icon,
  color = "blue",
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  color?: keyof typeof COLORS;
}) {
  return (
    <MetricCard
      label={title}
      value={value}
      sub={subtitle}
      icon={icon}
      iconClass={COLORS[color].icon}
    />
  );
}
