"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

/**
 * Manager dashboard: shows a quick "Create vacancy" action and a list of the
 * five most recent vacancies with links to their detail pages. Wrapped in the
 * HR_ADMIN auth guard.
 */
export default function ManagerHomePage() {
  const [vacancies, setVacancies] = useState<Vacancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load vacancies"));
  }, []);

  const recent = (vacancies ?? []).slice(0, 5);

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
            <p className="mt-1 text-sm text-muted">Manage your hiring pipeline.</p>
          </div>
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
          <p className="mt-6 text-sm text-muted">
            No vacancies yet.{" "}
            <Link href="/manager/vacancies/new" className="underline underline-offset-4 hover:text-foreground">
              Create your first one
            </Link>
            .
          </p>
        )}

        {recent.length > 0 && (
          <div className="mt-6 overflow-hidden rounded-xl border border-border">
            <div className="border-b border-border bg-surface px-5 py-3 text-xs font-medium uppercase tracking-wide text-muted">
              Recent vacancies
            </div>
            {recent.map((v) => (
              <Link
                key={v.vacancy_id}
                href={`/manager/vacancies/${v.vacancy_id}`}
                className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 transition-colors last:border-b-0 hover:bg-surface-hover"
              >
                <div>
                  <p className="text-sm font-medium">{v.title}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {v.department_name ?? "—"} · {v.employment_type.replace("_", " ")} · Closes{" "}
                    {formatDate(v.closing_date)}
                  </p>
                </div>
                <StatusBadge status={v.status} />
              </Link>
            ))}
            <Link
              href="/manager/vacancies"
              className="block border-t border-border px-5 py-3 text-xs font-medium text-muted transition-colors hover:text-foreground"
            >
              View all vacancies →
            </Link>
          </div>
        )}
      </div>
    </PortalGuard>
  );
}