const STATUS_STYLES: Record<string, string> = {
  APPLIED: "border-border text-muted",
  SHORTLISTED: "border-border-strong text-foreground",
  REJECTED: "border-danger/50 text-danger",
  DRAFT: "border-border text-muted",
  OPEN: "border-border-strong text-foreground",
  CLOSED: "border-border text-muted",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${STATUS_STYLES[status] ?? "border-border text-muted"}`}
    >
      {status.toLowerCase().replaceAll("_", " ")}
    </span>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
