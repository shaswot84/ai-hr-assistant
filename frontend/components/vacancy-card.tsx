import Link from "next/link";
import type { Vacancy } from "@/lib/types";
import { StatusBadge, formatDate } from "@/components/status";

export function VacancyCard({ vacancy, href }: { vacancy: Vacancy; href: string }) {
  return (
    <Link
      href={href}
      className="block rounded-xl border border-border bg-surface p-5 transition-colors hover:bg-surface-hover"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold">{vacancy.title}</h3>
          <p className="mt-0.5 text-xs text-muted">
            {vacancy.department_name ?? "—"} · {vacancy.employment_type.replace("_", " ")}
          </p>
        </div>
        <StatusBadge status={vacancy.status} />
      </div>
      {vacancy.description && (
        <p className="mt-3 line-clamp-2 text-sm text-muted">{vacancy.description}</p>
      )}
      <p className="mt-4 text-xs text-muted">
        Closes {formatDate(vacancy.closing_date)}
      </p>
    </Link>
  );
}