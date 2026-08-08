/** Small display helpers shared by the portal pages. */

export function statusBadgeClass(status: string | null | undefined): string {
  switch (String(status ?? "").toUpperCase()) {
    case "INDEXED":
      return "bg-green-100 text-green-700";
    case "FAILED":
      return "bg-red-100 text-red-700";
    case "PENDING":
    case "PROCESSING":
      return "bg-amber-100 text-amber-700";
    case "DELETED":
      return "bg-gray-100 text-gray-600";
    default:
      return "bg-gray-100 text-gray-600";
  }
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}
