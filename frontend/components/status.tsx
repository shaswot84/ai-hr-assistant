const COLORS: Record<string, string> = {
  OPEN: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  APPLIED: "bg-amber-50 text-amber-700 ring-amber-600/20",
  SHORTLISTED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  CLOSED: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  REJECTED: "bg-red-50 text-red-700 ring-red-600/20",
  WITHDRAWN: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  DRAFT: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  INDEXED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  PROCESSING: "bg-amber-50 text-amber-700 ring-amber-600/20",
  PENDING: "bg-amber-50 text-amber-700 ring-amber-600/20",
  FAILED: "bg-red-50 text-red-700 ring-red-600/20",
  DELETED: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  ACTIVE: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  INACTIVE: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
  APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  CANCELLED: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
};

/** A small status pill with a leading dot (vacancy / application / document status). */
export function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status.toUpperCase()] ?? "bg-zinc-100 text-zinc-600 ring-zinc-500/20";
  return (
    <span className={`badge ring-1 ring-inset ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  );
}
