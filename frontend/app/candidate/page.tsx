"use client";

import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { VacancyCard } from "@/components/vacancy-card";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

/**
 * Candidate landing page: lists currently OPEN vacancies from the API and
 * links each to its apply page. Wrapped in the candidate-only auth guard.
 */
export default function CandidateHomePage() {
  const [vacancies, setVacancies] = useState<Vacancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listVacancies()
      .then(setVacancies)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load vacancies"));
  }, []);

  // Candidates may only see and apply to vacancies that are currently OPEN.
  const open = (vacancies ?? []).filter((v) => v.status === "OPEN");

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="animate-fade-in">
        <h1 className="text-xl font-semibold tracking-tight">Open vacancies</h1>
        <p className="mt-1 text-sm text-muted">Browse current openings and apply with your resume.</p>

        {error && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!error && !vacancies && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {!error && vacancies && open.length === 0 && (
          <p className="mt-6 text-sm text-muted">No open vacancies right now.</p>
        )}

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {open.map((v) => (
            <VacancyCard key={v.vacancy_id} vacancy={v} href={`/candidate/vacancies/${v.vacancy_id}`} />
          ))}
        </div>
      </div>
    </PortalGuard>
  );
}