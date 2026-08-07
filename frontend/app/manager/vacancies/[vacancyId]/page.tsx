"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton, ListSkeleton } from "@/components/loading";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type { ApplicationDetail, Vacancy } from "@/lib/types";

function ArchiveButton({ vacancy, onChange }: { vacancy: Vacancy; onChange: (v: Vacancy) => void }) {
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const updated =
        vacancy.status === "OPEN"
          ? await api.closeVacancy(vacancy.vacancy_id)
          : await api.reopenVacancy(vacancy.vacancy_id);
      onChange(updated);
      addToast(
        updated.status === "OPEN" ? "Vacancy reopened." : "Vacancy closed.",
        "success"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <button type="button" onClick={toggle} disabled={busy} className="btn-secondary">
      {busy ? "Working…" : vacancy.status === "OPEN" ? "Close Vacancy" : "Reopen Vacancy"}
    </button>
  );
}

function ApplicationsList({ vacancyId }: { vacancyId: string }) {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .vacancyApplications(vacancyId)
      .then(setApplications)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load applications."));
  }, [vacancyId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (applications === null) return <ListSkeleton rows={3} />;
  if (applications.length === 0)
    return (
      <div className="card p-8 text-center">
        <p className="text-sm text-gray-500">No applications yet.</p>
      </div>
    );

  return (
    <div className="card divide-y divide-gray-100 overflow-hidden">
      {applications.map((a) => (
        <Link
          key={a.application_id}
          href={`/manager/applications/${a.application_id}`}
          className="flex items-center gap-3 px-6 py-4 transition-colors hover:bg-sky-50"
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-600">
            {(a.candidate_name ?? a.candidate_email ?? "?").charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-gray-900">{a.candidate_name ?? a.candidate_email}</p>
            <p className="mt-0.5 text-xs text-gray-500">
              Applied {new Date(a.applied_at).toLocaleDateString()}
              {a.evaluated && a.evaluation ? ` · match score ${a.evaluation.score}` : " · screening…"}
            </p>
          </div>
          <StatusBadge status={a.application_status} />
        </Link>
      ))}
    </div>
  );
}

export default function ManagerVacancyDetailPage() {
  const params = useParams<{ vacancyId: string }>();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getVacancy(params.vacancyId)
      .then(setVacancy)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Vacancy not found."));
  }, [params.vacancyId]);

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!error && !vacancy && <DetailSkeleton />}
      {vacancy && (
        <>
          <div className="card flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-gray-900">{vacancy.title}</h1>
                <StatusBadge status={vacancy.status} />
              </div>
              <p className="mt-1 text-sm text-gray-500">
                {vacancy.department_name ?? "—"} · {vacancy.employment_type.replaceAll("_", " ")}
              </p>
              {vacancy.description && (
                <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                  {vacancy.description}
                </p>
              )}
            </div>
            <ArchiveButton vacancy={vacancy} onChange={setVacancy} />
          </div>

          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-500">
              Applications
            </h2>
            <ApplicationsList vacancyId={vacancy.vacancy_id} />
          </div>
        </>
      )}
    </div>
  );
}
