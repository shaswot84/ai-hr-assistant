"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { ScoreRing } from "@/components/score-ring";
import { api } from "@/lib/api";
import type { ApplicationDetail } from "@/lib/types";

export default function ApplicationReviewPage({
  params,
}: {
  params: Promise<{ applicationId: string }>;
}) {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [app, setApp] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    params.then(({ applicationId }) => setApplicationId(applicationId));
  }, [params]);

  useEffect(() => {
    if (!applicationId) return;
    api
      .applicationDetail(applicationId)
      .then(setApp)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load application"));
  }, [applicationId]);

  async function decide(action: "approve" | "reject") {
    if (!applicationId) return;
    setActing(true);
    setError(null);
    try {
      await api.decide(applicationId, action);
      setApp(await api.applicationDetail(applicationId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update application");
    } finally {
      setActing(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in mx-auto max-w-2xl">
        <Link
          href={app ? `/manager/vacancies/${app.vacancy_id}` : "/manager/vacancies"}
          className="text-xs text-muted transition-colors hover:text-foreground"
        >
          ← Back to vacancy
        </Link>

        {error && !app && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!app && !error && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {app && (
          <>
            <div className="mt-4 flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold tracking-tight">
                  {app.candidate_name ?? "Candidate"}
                </h1>
                <p className="mt-1 text-sm text-muted">
                  {app.candidate_email ?? "—"} · {app.vacancy_title ?? "Vacancy"} · Applied{" "}
                  {formatDate(app.applied_at)}
                </p>
              </div>
              <StatusBadge status={app.application_status} />
            </div>

            <div className="mt-6 flex items-center justify-between rounded-xl border border-border bg-surface p-5">
              <div className="flex items-center gap-5">
                {app.evaluation && app.evaluation.score > 0 ? (
                  <>
                    <ScoreRing score={app.evaluation.score} />
                    <div>
                      <h2 className="text-sm font-semibold">AI resume evaluation</h2>
                      <p className="mt-0.5 text-xs text-muted">
                        Model: {app.evaluation.model ?? "fallback"} ·{" "}
                        {formatDate(app.evaluation.evaluated_at)}
                      </p>
                    </div>
                  </>
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full border border-border">
                      <span className="text-[10px] text-muted">no score</span>
                    </div>
                    <p className="text-sm text-muted">Evaluation pending.</p>
                  </div>
                )}
              </div>
              {app.application_id && (
                <a
                  href={api.resumeUrl(app.application_id)}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-border px-3.5 py-1.5 text-xs font-medium transition-colors hover:bg-surface-hover"
                >
                  View resume
                </a>
              )}
            </div>

            {app.evaluation?.overview && (
              <div className="mt-4 rounded-xl border border-border bg-surface p-5">
                <h2 className="text-xs font-medium uppercase tracking-wide text-muted">Overview</h2>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
                  {app.evaluation.overview}
                </p>
              </div>
            )}

            {app.application_status === "APPLIED" ? (
              <div className="mt-6 flex gap-3">
                <button
                  type="button"
                  onClick={() => decide("approve")}
                  disabled={acting}
                  className="flex-1 rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {acting ? "Updating…" : "Approve & shortlist"}
                </button>
                <button
                  type="button"
                  onClick={() => decide("reject")}
                  disabled={acting}
                  className="flex-1 rounded-full border border-danger/60 px-5 py-2.5 text-sm font-medium text-danger transition-colors hover:bg-surface-hover disabled:opacity-40"
                >
                  Reject
                </button>
              </div>
            ) : (
              <div className="mt-6 flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3">
                <p className="text-sm text-muted">
                  Decision made: <span className="capitalize text-foreground">{app.application_status.toLowerCase()}</span>.
                </p>
                <Link
                  href="/manager"
                  className="text-xs font-medium text-muted underline underline-offset-4 transition-colors hover:text-foreground"
                >
                  Back to dashboard
                </Link>
              </div>
            )}

            {error && <p className="mt-4 text-sm text-danger">{error}</p>}

            {(app.application_status === "SHORTLISTED" || app.application_status === "REJECTED") && (
              <p className="mt-3 text-xs text-muted">
                The candidate has been notified by email.
              </p>
            )}
          </>
        )}
      </div>
    </PortalGuard>
  );
}