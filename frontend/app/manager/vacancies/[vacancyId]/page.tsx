"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { ScoreRing } from "@/components/score-ring";
import { api } from "@/lib/api";
import type { ApplicationDetail, Vacancy } from "@/lib/types";

/**
 * Manager vacancy detail page: shows the vacancy info plus a list of its
 * applications with scores, linking each to the review page. Applications
 * that fail to load default to an empty list. Wrapped in the HR_ADMIN guard.
 *
 * @param props.params Next.js route params resolving to the vacancy id.
 */
export default function ManagerVacancyDetailPage({
  params,
}: {
  params: Promise<{ vacancyId: string }>;
}) {
  const [vacancyId, setVacancyId] = useState<string | null>(null);
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  // Next.js 15+ provides params as a promise; unwrap it into state.
  useEffect(() => {
    params.then(({ vacancyId }) => setVacancyId(vacancyId));
  }, [params]);

  useEffect(() => {
    if (!vacancyId) return;
    api
      .getVacancy(vacancyId)
      .then(setVacancy)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load vacancy"));
  }, [vacancyId]);

  useEffect(() => {
    if (!vacancyId) return;
    api
      .vacancyApplications(vacancyId)
      .then(setApplications)
      .catch(() => setApplications([]));
  }, [vacancyId]);

  /** Archives the vacancy (move to CLOSED) or re-opens it, then refreshes its detail. */
  async function toggleClosed() {
    if (!vacancyId) return;
    setActing(true);
    setError(null);
    try {
      const updated = vacancy?.status === "OPEN" ? await api.closeVacancy(vacancyId) : await api.reopenVacancy(vacancyId);
      setVacancy(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update vacancy");
    } finally {
      setActing(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in mx-auto max-w-3xl">
        <Link href="/manager/vacancies" className="text-xs text-muted transition-colors hover:text-foreground">
          ← Back to vacancies
        </Link>

        {error && !vacancy && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!vacancy && !error && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {vacancy && (
          <>
            <div className="mt-4 flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold tracking-tight">{vacancy.title}</h1>
                <p className="mt-1 text-sm text-muted">
                  {vacancy.department_name ?? "—"} · {vacancy.employment_type.replace("_", " ")} ·
                  Closes {formatDate(vacancy.closing_date)}
                </p>
              </div>
              <StatusBadge status={vacancy.status} />
            </div>

            {error && <p className="mt-2 text-sm text-danger">{error}</p>}

            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={toggleClosed}
                disabled={acting}
                className="rounded-full border border-border px-4 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-hover disabled:opacity-50"
              >
                {acting
                  ? "Updating…"
                  : vacancy.status === "OPEN"
                    ? "Close vacancy"
                    : "Reopen vacancy"}
              </button>
            </div>

            {vacancy.description && (
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-muted">
                {vacancy.description}
              </p>
            )}

            <div className="mt-8 flex items-center justify-between">
              <h2 className="text-sm font-semibold">
                Applications{" "}
                <span className="font-normal text-muted">
                  ({applications?.length ?? 0})
                </span>
              </h2>
            </div>

            {!applications && <p className="mt-4 text-sm text-muted">Loading…</p>}

            {applications && applications.length === 0 && (
              <p className="mt-4 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
                No applications yet.
              </p>
            )}

            <div className="mt-4 space-y-3">
              {applications?.map((app) => (
                <Link
                  key={app.application_id}
                  href={`/manager/applications/${app.application_id}`}
                  className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface p-5 transition-colors hover:bg-surface-hover"
                >
                  <div className="flex items-center gap-4">
                    {app.evaluation && app.evaluation.score > 0 ? (
                      <ScoreRing score={app.evaluation.score} />
                    ) : (
                      <div className="flex h-20 w-20 shrink-0 items-center justify-center">
                        <span className="text-[10px] text-muted">no score</span>
                      </div>
                    )}
                    <div>
                      <p className="text-sm font-medium">
                        {app.candidate_name ?? "Candidate"} · {app.candidate_email ?? "—"}
                      </p>
                      <p className="mt-0.5 text-xs text-muted">Applied {formatDate(app.applied_at)}</p>
                    </div>
                  </div>
                  <StatusBadge status={app.application_status} />
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    </PortalGuard>
  );
}