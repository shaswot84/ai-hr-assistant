"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { VacancyCard } from "@/components/vacancy-card";
import { GridSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { api, ApiError } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

function VacancyList() {
  const [vacancies, setVacancies] = useState<Vacancy[] | null>(null);
  const [appliedVacancyIds, setAppliedVacancyIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load vacancies."));
    api
      .myApplications()
      .then((apps) => setAppliedVacancyIds(new Set(apps.map((a) => a.vacancy_id))))
      .catch(() => setAppliedVacancyIds(new Set()));
  }, []);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (vacancies === null) return <GridSkeleton />;
  if (vacancies.length === 0)
    return (
      <div className="card">
        <EmptyState
          title="No open vacancies right now"
          description="Check back soon — new roles are posted regularly."
        />
      </div>
    );

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {vacancies.map((v) => (
        <VacancyCard
          key={v.vacancy_id}
          vacancy={v}
          href={`/candidate/vacancies/${v.vacancy_id}`}
          applied={appliedVacancyIds.has(v.vacancy_id)}
        />
      ))}
    </div>
  );
}

export default function CandidateHomePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Open Vacancies"
        description="Browse open roles and apply with your resume."
      />
      <VacancyList />
    </div>
  );
}
