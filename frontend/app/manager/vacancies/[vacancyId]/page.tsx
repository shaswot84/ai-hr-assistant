"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { api, ApiError } from "@/lib/api";
import type { ApplicationDetail, Vacancy } from "@/lib/types";

function ArchiveButton({ vacancy, onChange }: { vacancy: Vacancy; onChange: (v: Vacancy) => void }) {
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const updated =
        vacancy.status === "OPEN" ? await api.closeVacancy(vacancy.vacancy_id) : await api.reopenVacancy(vacancy.vacancy_id);
      onChange(updated);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium transition-colors hover:bg-surface-hover disabled:opacity-50"
    >
      {busy ? "Working…" : vacancy.status === "OPEN" ? "Close vacancy" : "Reopen vacancy"}
    </button>
  );
}

function ApplicationsTable({ vacancyId }: { vacancyId: string }) {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .vacancyApplications(vacancyId)
      .then(setApplications)
      .catch((err) =>
        setError(err instanceof ApiError ? err.detail : "Failed to load applications.")
      );
  }, [vacancyId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (applications === null) return <p className="text-sm text-muted">Loading applications…</p>;
  if (applications.length === 0)
    return <p className="text-sm text-muted">No applications yet.</p>;

  return (
    <div className="divide-y divide-border rounded-xl border border-border bg-surface">
      {applications.map((a) => (
        <Link
          key={a.application_id}
          href={`/manager/applications/${a.application_id}`}
          className="flex items-center justify-between gap-3 p-4 transition-colors hover:bg-surface-hover"
        >
          <div>
            <p className="font-medium">{a.candidate_name ?? a.candidate_email ?? "Candidate"}</p>
            <p className="mt-0.5 text-xs text-muted">
              Applied {new Date(a.applied_at).toLocaleDateString()}
              {a.evaluated && a.evaluation ? ` · AI score ${a.evaluation.score}` : " · evaluating…"}
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
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!error && !vacancy && <p className="text-sm text-muted">Loading…</p>}
      {vacancy && (
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-semibold">{vacancy.title}</h1>
                <StatusBadge status={vacancy.status} />
              </div>
              <p className="mt-1 text-sm text-muted">
                {vacancy.department_name ?? "—"} · {vacancy.employment_type.replaceAll("_", " ")}
              </p>
            </div>
            <ArchiveButton vacancy={vacancy} onChange={setVacancy} />
          </div>
          {vacancy.description && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{vacancy.description}</p>
          )}
          <div>
            <h2 className="mb-2 text-sm font-medium">Applications</h2>
            <ApplicationsTable vacancyId={vacancy.vacancy_id} />
          </div>
        </div>
      )}
    </PortalGuard>
  );
}
