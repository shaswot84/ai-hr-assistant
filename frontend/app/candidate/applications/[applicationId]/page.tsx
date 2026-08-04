"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { ScoreRing } from "@/components/score-ring";
import { api } from "@/lib/api";
import type { ApplicationDetail } from "@/lib/types";

/**
 * Candidate single-application detail page. Shows the applied vacancy, its
 * status, the AI resume evaluation (score ring + overview) when available, and
 * a status-specific message for shortlisted/rejected applications.
 *
 * @param props.params Next.js route params resolving to the application id.
 */
export default function MyApplicationDetailPage({
  params,
}: {
  params: Promise<{ applicationId: string }>;
}) {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [app, setApp] = useState<ApplicationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Next.js 15+ provides params as a promise; unwrap it into state.
  useEffect(() => {
    params.then(({ applicationId }) => setApplicationId(applicationId));
  }, [params]);

  useEffect(() => {
    if (!applicationId) return;
    api
      .myApplication(applicationId)
      .then(setApp)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load application"));
  }, [applicationId]);

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="animate-fade-in mx-auto max-w-2xl">
        <Link
          href="/candidate/applications"
          className="text-xs text-muted transition-colors hover:text-foreground"
        >
          ← Back to applications
        </Link>

        {error && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!app && !error && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {app && (
          <>
            <div className="mt-4 flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold tracking-tight">{app.vacancy_title ?? "Vacancy"}</h1>
                <p className="mt-1 text-sm text-muted">Applied {formatDate(app.applied_at)}</p>
              </div>
              <StatusBadge status={app.application_status} />
            </div>

            {app.evaluation && (
              <div className="mt-6 rounded-xl border border-border bg-surface p-5">
                <div className="flex items-center gap-5">
                  <ScoreRing score={app.evaluation.score} />
                  <div>
                    <h2 className="text-sm font-semibold">Resume evaluation</h2>
                    <p className="mt-0.5 text-xs text-muted">
                      Model: {app.evaluation.model ?? "fallback"} · {formatDate(app.evaluation.evaluated_at)}
                    </p>
                  </div>
                </div>
                <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-muted">
                  {app.evaluation.overview}
                </p>
              </div>
            )}

            {app.application_status === "SHORTLISTED" && (
              <p className="mt-6 rounded-xl border border-border-strong bg-surface px-4 py-3 text-sm">
                Congratulations — your application was shortlisted! You will be notified by email
                about interview scheduling.
              </p>
            )}
            {app.application_status === "REJECTED" && (
              <p className="mt-6 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
                We appreciate your interest, but this position has been filled by another candidate.
              </p>
            )}
          </>
        )}
      </div>
    </PortalGuard>
  );
}