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
    <Link href={href} className="card block p-5 transition-shadow duration-200 hover:shadow-md">
      <div className="flex items-start gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-lg font-bold text-blue-600">
          {vacancy.title.charAt(0)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="truncate font-semibold text-gray-900">{vacancy.title}</p>
            <div className="flex shrink-0 gap-1.5">
              {applied && <StatusBadge status="APPLIED" />}
              <StatusBadge status={vacancy.status} />
            </div>
          </div>
          <p className="text-sm text-gray-500">
            {vacancy.department_name ?? "—"} · {vacancy.employment_type.replaceAll("_", " ")}
          </p>
        </div>
      </div>
      {vacancy.description && (
        <p className="mt-3 line-clamp-2 text-sm text-gray-600">{vacancy.description}</p>
      )}
    </Link>
  );
}
