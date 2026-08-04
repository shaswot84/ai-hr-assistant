"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { ScoreRing } from "@/components/score-ring";
import { api } from "@/lib/api";
import type { Application } from "@/lib/types";

/**
 * Candidate "My applications" page: lists the current candidate's submitted
 * applications with their score ring (when evaluated) and status. Wrapped in
 * the candidate-only auth guard.
 */
export default function MyApplicationsPage() {
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myApplications()
      .then(setApplications)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load applications"));
  }, []);

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="animate-fade-in">
        <h1 className="text-xl font-semibold tracking-tight">My applications</h1>
        <p className="mt-1 text-sm text-muted">Track the status of every application you have submitted.</p>

        {error && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!error && !applications && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {!error && applications && applications.length === 0 && (
          <p className="mt-6 text-sm text-muted">
            You have not applied anywhere yet.{" "}
            <Link href="/candidate" className="underline underline-offset-4 hover:text-foreground">
              Browse vacancies
            </Link>
            .
          </p>
        )}

        <div className="mt-6 space-y-4">
          {applications?.map((app) => (
            <Link
              key={app.application_id}
              href={`/candidate/applications/${app.application_id}`}
              className="block rounded-xl border border-border bg-surface p-5 transition-colors hover:bg-surface-hover"
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold">{app.vacancy_title ?? "Vacancy"}</h3>
                  <p className="mt-0.5 text-xs text-muted">Applied {formatDate(app.applied_at)}</p>
                </div>
                <div className="flex items-center gap-3">
                  {app.evaluation && app.evaluation.score > 0 && (
                    <ScoreRing score={app.evaluation.score} />
                  )}
                  <StatusBadge status={app.application_status} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </PortalGuard>
  );
}