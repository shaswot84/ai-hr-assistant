"use client";

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
  if (vacancies === null) return <p className="text-sm text-muted">Loading vacancies…</p>;
  if (vacancies.length === 0) return <p className="text-sm text-muted">No open vacancies right now.</p>;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {vacancies.map((v) => (
        <VacancyCard key={v.vacancy_id} vacancy={v} href={`/candidate/vacancies/${v.vacancy_id}`} />
      ))}
    </div>
  );
}

export default function CandidateHomePage() {
  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Open vacancies</h1>
        <p className="mt-1 text-sm text-muted">Browse open roles and apply with your resume.</p>
      </div>
      <VacancyList />
    </PortalGuard>
  );
}
