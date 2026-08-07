const COLORS: Record<string, string> = {
  OPEN: "bg-green-100 text-green-700",
  APPLIED: "bg-amber-100 text-amber-700",
  SHORTLISTED: "bg-green-100 text-green-700",
  CLOSED: "bg-gray-100 text-gray-600",
  REJECTED: "bg-red-100 text-red-700",
  WITHDRAWN: "bg-gray-100 text-gray-600",
  DRAFT: "bg-gray-100 text-gray-600",
};

/** A small colored status pill (vacancy or application status). */
export function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`badge ${cls}`}>
      {status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  );
}
