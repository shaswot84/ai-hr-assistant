"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

export default function VacanciesListPage() {
  const [vacancies, setVacancies] = useState<Vacancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load vacancies"));
  }, []);

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in">
        <div className="flex items-center justify-between gap-4">
          <h1 className="text-xl font-semibold tracking-tight">Vacancies</h1>
          <Link
            href="/manager/vacancies/new"
            className="rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
          >
            Create vacancy
          </Link>
        </div>

        {error && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!error && !vacancies && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {!error && vacancies && vacancies.length === 0 && (
          <p className="mt-6 text-sm text-muted">No vacancies yet.</p>
        )}

        <div className="mt-6 space-y-4">
          {vacancies?.map((v) => (
            <Link
              key={v.vacancy_id}
              href={`/manager/vacancies/${v.vacancy_id}`}
              className="block rounded-xl border border-border bg-surface p-5 transition-colors hover:bg-surface-hover"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold">{v.title}</h3>
                  <p className="mt-0.5 text-xs text-muted">
                    {v.department_name ?? "—"} · {v.employment_type.replace("_", " ")} · Created{" "}
                    {formatDate(v.created_at)}
                  </p>
                </div>
                <StatusBadge status={v.status} />
              </div>
              {v.description && (
                <p className="mt-3 line-clamp-2 text-sm text-muted">{v.description}</p>
              )}
            </Link>
          ))}
        </div>
      </div>
    </PortalGuard>
  );
}