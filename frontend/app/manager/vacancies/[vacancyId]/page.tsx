"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { BackLink } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton, ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
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

const RECOMMENDATION_TONE: Record<string, string> = {
  "Strong Match": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Good Match": "bg-blue-50 text-blue-700 ring-blue-600/20",
  "Possible Match": "bg-amber-50 text-amber-700 ring-amber-600/20",
  "Weak Match": "bg-red-50 text-red-700 ring-red-600/20",
};

function ApplicationsList({ vacancyId }: { vacancyId: string }) {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .vacancyApplications(vacancyId)
      .then(setApplications)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load applications."));
  }, [vacancyId]);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (applications === null) return <ListSkeleton rows={3} />;
  if (applications.length === 0)
    return (
      <div className="card">
        <EmptyState
          title="No applications yet"
          description="Candidates will appear here once they start applying to this role."
        />
      </div>
    );

  return (
    <div className="card overflow-hidden">
      <div className="table-scroll">
        <table className="w-full">
          <thead className="bg-zinc-50">
            <tr>
              <th className="table-th">Candidate</th>
              <th className="table-th hidden sm:table-cell">Applied</th>
              <th className="table-th hidden sm:table-cell">Match</th>
              <th className="table-th">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {applications.map((a) => (
              <tr key={a.application_id} className="table-row">
                <td className="table-td">
                  <Link
                    href={`/manager/applications/${a.application_id}`}
                    className="flex items-center gap-3"
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-[13px] font-semibold text-zinc-600">
                      {(a.candidate_name ?? a.candidate_email ?? "?").charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <p className="truncate font-medium text-zinc-900 hover:text-blue-600">
                        {a.candidate_name ?? a.candidate_email}
                      </p>
                      {a.evaluated && a.evaluation ? (
                        <p className="text-xs text-zinc-400">AI screened</p>
                      ) : (
                        <p className="text-xs text-zinc-400">screening…</p>
                      )}
                    </div>
                  </Link>
                </td>
                <td className="table-td hidden text-xs text-zinc-500 sm:table-cell">
                  {new Date(a.applied_at).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })}
                </td>
                <td className="table-td hidden sm:table-cell">
                  {!a.evaluated || !a.evaluation ? (
                    <span className="text-xs text-zinc-400">—</span>
                  ) : a.evaluation.failed ? (
                    <span
                      className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20"
                      title={a.evaluation.overview}
                    >
                      Failed
                    </span>
                  ) : a.evaluation.detail && !a.evaluation.detail.requirements_met ? (
                    <span className="badge bg-red-100 text-red-800 ring-1 ring-inset ring-red-600/30">
                      Doesn&apos;t meet reqs
                    </span>
                  ) : (
                    <span
                      className={`badge ring-1 ring-inset ${RECOMMENDATION_TONE[a.evaluation.detail?.recommendation ?? ""] ?? "bg-zinc-100 text-zinc-600 ring-zinc-500/20"}`}
                    >
                      {a.evaluation.detail?.recommendation ?? "Reviewed"}
                    </span>
                  )}
                </td>
                <td className="table-td">
                  <StatusBadge status={a.application_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !vacancy && <DetailSkeleton />}
      {vacancy && (
        <>
          <BackLink href="/manager/vacancies" label="All vacancies" />

          <div className="card p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
                    {vacancy.title}
                  </h1>
                  <StatusBadge status={vacancy.status} />
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-zinc-500">
                  <span className="font-medium text-zinc-700">{vacancy.department_name ?? "—"}</span>
                  <span className="text-zinc-300">·</span>
                  <span>{vacancy.employment_type.replaceAll("_", " ")}</span>
                  <span className="text-zinc-300">·</span>
                  <span>
                    Posted{" "}
                    {new Date(vacancy.created_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </span>
                </div>
                {vacancy.description && (
                  <p className="mt-4 max-w-3xl whitespace-pre-wrap text-sm leading-relaxed text-zinc-600">
                    {vacancy.description}
                  </p>
                )}
              </div>
              <div className="shrink-0">
                <ArchiveButton vacancy={vacancy} onChange={setVacancy} />
              </div>
            </div>
          </div>

          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
                Applications
              </h2>
            </div>
            <ApplicationsList vacancyId={vacancy.vacancy_id} />
          </div>
        </>
      )}
    </div>
  );
}
