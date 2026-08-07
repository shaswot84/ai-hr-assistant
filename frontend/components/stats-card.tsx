const COLORS = {
  blue: { bg: "bg-blue-50", icon: "text-blue-600", border: "border-blue-100" },
  green: { bg: "bg-green-50", icon: "text-green-600", border: "border-green-100" },
  amber: { bg: "bg-amber-50", icon: "text-amber-600", border: "border-amber-100" },
  purple: { bg: "bg-purple-50", icon: "text-purple-600", border: "border-purple-100" },
} as const;

/** A dashboard summary tile: title, big value, optional subtitle, and a colored icon chip. */
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
  const c = COLORS[color];
  return (
    <div className="card p-6 transition-shadow duration-200 hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
          {subtitle && <p className="mt-1 text-xs text-gray-500">{subtitle}</p>}
        </div>
        <div className={`rounded-xl border p-3 ${c.bg} ${c.border}`}>
          <span className={c.icon}>{icon}</span>
        </div>
      </div>
    </div>
  );
}
