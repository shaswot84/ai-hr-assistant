const COLORS: Record<string, string> = {
  OPEN: "bg-emerald-50 text-emerald-700 border-emerald-200",
  APPLIED: "bg-amber-50 text-amber-700 border-amber-200",
  SHORTLISTED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  CLOSED: "bg-neutral-100 text-neutral-600 border-neutral-200",
  REJECTED: "bg-red-50 text-red-700 border-red-200",
  WITHDRAWN: "bg-neutral-100 text-neutral-600 border-neutral-200",
  DRAFT: "bg-neutral-100 text-neutral-600 border-neutral-200",
};

/** A small colored status pill (vacancy or application status). */
export function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? "bg-neutral-100 text-neutral-600 border-neutral-200";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${cls}`}
    >
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  );
}
