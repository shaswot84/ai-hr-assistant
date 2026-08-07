const SIZES = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-10 w-10" } as const;

/** A small inline spinner. */
export function Spinner({ size = "md", className = "" }: { size?: keyof typeof SIZES; className?: string }) {
  return (
    <svg className={`animate-spin text-blue-600 ${SIZES[size]} ${className}`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

/** A full-section centered spinner, for single-item detail pages while loading. */
export function PageLoader() {
  return (
    <div className="flex min-h-[300px] flex-1 items-center justify-center">
      <Spinner size="lg" />
    </div>
  );
}

/** Pulsing bars standing in for list/table rows. */
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="card animate-pulse divide-y divide-gray-100 overflow-hidden">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-6 py-4">
          <div className="h-9 w-9 shrink-0 rounded-full bg-gray-200" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-1/3 rounded bg-gray-200" />
            <div className="h-2.5 w-1/4 rounded bg-gray-100" />
          </div>
          <div className="h-5 w-16 rounded-full bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

/** Pulsing card-shaped placeholders standing in for a vacancy-card grid. */
export function GridSkeleton({ items = 4 }: { items?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="card animate-pulse p-5">
          <div className="flex items-start gap-3">
            <div className="h-12 w-12 shrink-0 rounded-xl bg-gray-200" />
            <div className="flex-1 space-y-2">
              <div className="h-3.5 w-2/3 rounded bg-gray-200" />
              <div className="h-2.5 w-1/2 rounded bg-gray-100" />
            </div>
          </div>
          <div className="mt-4 h-2.5 w-full rounded bg-gray-100" />
          <div className="mt-2 h-2.5 w-4/5 rounded bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

/** Pulsing stat-card placeholders for a dashboard summary row. */
export function StatsSkeleton({ items = 3 }: { items?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="card animate-pulse p-6">
          <div className="h-3 w-1/2 rounded bg-gray-200" />
          <div className="mt-3 h-7 w-1/3 rounded bg-gray-200" />
          <div className="mt-3 h-2.5 w-2/3 rounded bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

/** A pulsing placeholder for a header/detail card (title + a couple of lines). */
export function DetailSkeleton() {
  return (
    <div className="card animate-pulse p-6">
      <div className="h-5 w-1/3 rounded bg-gray-200" />
      <div className="mt-3 h-3 w-1/4 rounded bg-gray-100" />
      <div className="mt-5 space-y-2">
        <div className="h-2.5 w-full rounded bg-gray-100" />
        <div className="h-2.5 w-5/6 rounded bg-gray-100" />
        <div className="h-2.5 w-2/3 rounded bg-gray-100" />
      </div>
    </div>
  );
}
