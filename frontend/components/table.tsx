"use client";

export type SortState = { key: string; dir: "asc" | "desc" };

/** Toggle helper — pass into a sortable column header. */
export function toggleSort(current: SortState, key: string): SortState {
  if (current.key !== key) return { key, dir: "asc" };
  return { key, dir: current.dir === "asc" ? "desc" : "asc" };
}

/** A sortable column header button wired to a shared SortState. */
export function SortableTh({
  children,
  sortKey,
  sort,
  onSort,
  className = "",
  align = "left",
}: {
  children: React.ReactNode;
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  return (
    <th
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={`table-th ${align === "right" ? "text-right" : ""} ${className}`}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`th-button ${active ? "text-zinc-800" : ""}`}
      >
        {children}
        <svg
          className={`h-3 w-3 transition-opacity ${
            active ? "text-blue-600 opacity-100" : "opacity-0 group-hover:opacity-40"
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          style={active ? { transform: sort.dir === "desc" ? "rotate(180deg)" : undefined } : undefined}
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>
    </th>
  );
}

/** A plain (non-sortable) table header cell. */
export function Th({
  children,
  className = "",
  align = "left",
}: {
  children?: React.ReactNode;
  className?: string;
  align?: "left" | "right";
}) {
  return (
    <th className={`table-th ${align === "right" ? "text-right" : ""} ${className}`}>
      {children}
    </th>
  );
}
