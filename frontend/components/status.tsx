/** Tailwind classes per status value; unknown statuses fall back to a neutral style. */
const STATUS_STYLES: Record<string, string> = {
  APPLIED: "border-border text-muted",
  SHORTLISTED: "border-border-strong text-foreground",
  REJECTED: "border-danger/50 text-danger",
  DRAFT: "border-border text-muted",
  OPEN: "border-border-strong text-foreground",
  CLOSED: "border-border text-muted",
};

/**
 * Pill-shaped badge that displays a status (e.g. APPLIED, OPEN) with a
 * status-specific color and a humanized label ("Shortlisted").
 *
 * @param props.status The raw status string from the API.
 */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${STATUS_STYLES[status] ?? "border-border text-muted"}`}
    >
      {status.toLowerCase().replaceAll("_", " ")}
    </span>
  );
}

/**
 * Formats an ISO date string as a localized short date (e.g. "Aug 4, 2026").
 * Returns an em-dash for missing/invalid values.
 *
 * @param value ISO date string, or null/undefined.
 * @returns Formatted date string or "—".
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
