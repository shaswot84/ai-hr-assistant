"use client";

/** Compact pagination: "Showing X–Y of Z" plus prev/next and page numbers. */
export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, pageCount);
  const from = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const to = Math.min(current * pageSize, total);

  const pages: Array<number | "…"> = [];
  for (let i = 1; i <= pageCount; i++) {
    if (i === 1 || i === pageCount || Math.abs(i - current) <= 1) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "…") {
      pages.push("…");
    }
  }

  const btn =
    "inline-flex h-7 min-w-7 items-center justify-center rounded-md px-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="flex flex-col items-center justify-between gap-3 border-t border-zinc-100 px-4 py-3 sm:flex-row">
      <p className="text-xs tabular-nums text-zinc-400">
        Showing <span className="font-medium text-zinc-600">{from}</span>–
        <span className="font-medium text-zinc-600">{to}</span> of{" "}
        <span className="font-medium text-zinc-600">{total}</span>
      </p>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className={`${btn} text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900`}
          disabled={current <= 1}
          onClick={() => onPage(current - 1)}
          aria-label="Previous page"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        {pages.map((p, i) =>
          p === "…" ? (
            <span key={`e${i}`} className="px-1 text-xs text-zinc-400">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onPage(p)}
              className={`${btn} ${
                p === current
                  ? "bg-zinc-900 text-white"
                  : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
              }`}
            >
              {p}
            </button>
          )
        )}
        <button
          type="button"
          className={`${btn} text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900`}
          disabled={current >= pageCount}
          onClick={() => onPage(current + 1)}
          aria-label="Next page"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
