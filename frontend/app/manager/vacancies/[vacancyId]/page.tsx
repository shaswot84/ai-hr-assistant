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
import type { ApplicationDetail, KeywordTier, Vacancy } from "@/lib/types";

const KEYWORD_TIER_TONE: Record<KeywordTier, string> = {
  critical: "bg-red-50 text-red-700 ring-red-600/20",
  important: "bg-amber-50 text-amber-700 ring-amber-600/20",
  nice_to_have: "bg-zinc-100 text-zinc-600 ring-zinc-500/20",
};

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

function scoreTone(score: number) {
  if (score >= 70) return "text-emerald-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

/** Ranking within a single list (requirements-met and requirements-failed
 * are now entirely separate lists, so this only ever ranks within one
 * tier at a time): higher weighted keyword score first; unscored/failed
 * screenings sink to the bottom. */
function matchQuality(a: ApplicationDetail): number {
  if (!a.evaluated || !a.evaluation || a.evaluation.failed) return -1;
  return a.evaluation.keyword_score ?? 0;
}

/** A candidate who clearly failed a stated hard requirement — kept in a
 * separate list entirely from everyone else, so a manager scanning who's
 * still in the running doesn't have to look past eliminated candidates. */
function failsRequirements(a: ApplicationDetail): boolean {
  return (
    a.evaluated && !!a.evaluation && !a.evaluation.failed && a.evaluation.detail?.requirements_met === false
  );
}

function ApplicationsTable({ rows }: { rows: ApplicationDetail[] }) {
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
            {rows.map((a) => (
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
                  ) : a.evaluation.keyword_score !== null ? (
                    <span className={`font-semibold tabular-nums ${scoreTone(a.evaluation.keyword_score)}`}>
                      {a.evaluation.keyword_score}%
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

function ApplicationsList({ vacancyId }: { vacancyId: string }) {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedExpanded, setFailedExpanded] = useState(false);

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

  const meeting = applications
    .filter((a) => !failsRequirements(a))
    .sort((a, b) => matchQuality(b) - matchQuality(a));
  const failing = applications.filter(failsRequirements).sort((a, b) => matchQuality(b) - matchQuality(a));

  return (
    <div className="space-y-4">
      {meeting.length > 0 && <ApplicationsTable rows={meeting} />}

      {/* Kept as a fully separate, collapsed-by-default section (not just
          sorted below) — a manager scanning who's still in the running
          shouldn't have to look past eliminated candidates to find them. */}
      {failing.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setFailedExpanded((v) => !v)}
            className="mb-3 flex w-full items-center gap-2 text-left"
            aria-expanded={failedExpanded}
          >
            <svg
              className={`h-4 w-4 shrink-0 text-zinc-400 transition-transform ${failedExpanded ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <h3 className="text-sm font-semibold text-red-800">Doesn&apos;t Meet Requirements</h3>
            <span className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20">
              {failing.length}
            </span>
          </button>
          {failedExpanded && <ApplicationsTable rows={failing} />}
        </div>
      )}
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
                {vacancy.scoring_keywords.length > 0 && (
                  <div className="mt-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                      Scoring Keywords
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {vacancy.scoring_keywords.map((kw) => (
                        <span
                          key={kw.keyword}
                          className={`badge ring-1 ring-inset ${KEYWORD_TIER_TONE[kw.tier]}`}
                        >
                          {kw.keyword}
                        </span>
                      ))}
                    </div>
                  </div>
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
