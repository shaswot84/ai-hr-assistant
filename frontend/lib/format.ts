/** Small display helpers shared by the portal pages. */

export function statusBadgeClass(status: string | null | undefined): string {
  switch (String(status ?? "").toUpperCase()) {
    case "INDEXED":
      return "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20";
    case "FAILED":
      return "bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20";
    case "PENDING":
    case "PROCESSING":
      return "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20";
    case "DELETED":
      return "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20";
    default:
      return "bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20";
  }
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}
