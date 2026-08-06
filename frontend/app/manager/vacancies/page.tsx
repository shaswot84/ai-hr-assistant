"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { VacancyCard } from "@/components/vacancy-card";
import { api, ApiError } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

function VacancyList() {
  const [vacancies, setVacancies] = useState<Vacancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load vacancies."));
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (vacancies === null) return <p className="text-sm text-muted">Loading…</p>;
  if (vacancies.length === 0) return <p className="text-sm text-muted">No vacancies yet.</p>;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {vacancies.map((v) => (
        <VacancyCard key={v.vacancy_id} vacancy={v} href={`/manager/vacancies/${v.vacancy_id}`} />
      ))}
    </div>
  );
}

export default function ManagerVacanciesPage() {
  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Vacancies</h1>
          <p className="mt-1 text-sm text-muted">All vacancies, open and closed.</p>
        </div>
        <Link
          href="/manager/vacancies/new"
          className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          Post a vacancy
        </Link>
      </div>
      <VacancyList />
    </PortalGuard>
  );
}
