/** A quiet, centered empty state used across tables and lists. */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-6 py-14 text-center">
      {icon && (
        <div className="mb-2 flex h-11 w-11 items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50 text-zinc-400">
          {icon}
        </div>
      )}
      <p className="text-sm font-medium text-zinc-900">{title}</p>
      {description && <p className="max-w-sm text-[13px] leading-relaxed text-zinc-500">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
