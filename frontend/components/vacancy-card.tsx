import Link from "next/link";
import type { Vacancy } from "@/lib/types";
import { StatusBadge } from "@/components/status";

/** A clickable summary card for one vacancy, linking into its detail page. */
export function VacancyCard({
  vacancy,
  href,
  applied = false,
}: {
  vacancy: Vacancy;
  href: string;
  applied?: boolean;
}) {
  return (
    <Link
      href={href}
      className="card group block p-5 transition-colors duration-150 hover:border-zinc-300"
    >
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-base font-semibold text-blue-600 transition-colors group-hover:bg-blue-50">
          {vacancy.title.charAt(0)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate font-medium text-zinc-900">{vacancy.title}</p>
            <div className="flex shrink-0 gap-1.5">
              {applied && <StatusBadge status="APPLIED" />}
              <StatusBadge status={vacancy.status} />
            </div>
          </div>
          <p className="mt-0.5 text-[13px] text-zinc-500">
            {vacancy.department_name ?? "—"} · {vacancy.employment_type.replaceAll("_", " ")}
          </p>
        </div>
      </div>
      {vacancy.description && (
        <p className="mt-3 line-clamp-2 text-[13px] leading-relaxed text-zinc-500">
          {vacancy.description}
        </p>
      )}
      <span className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-blue-600 opacity-0 transition-opacity group-hover:opacity-100">
        View role
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </span>
    </Link>
  );
}
