"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { api, ApiError } from "@/lib/api";
import type { Application } from "@/lib/types";

function ApplicationsList() {
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myApplications()
      .then(setApplications)
      .catch((err) =>
        setError(err instanceof ApiError ? err.detail : "Failed to load applications.")
      );
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (applications === null) return <p className="text-sm text-muted">Loading…</p>;
  if (applications.length === 0)
    return <p className="text-sm text-muted">You haven&apos;t applied to any vacancies yet.</p>;

  return (
    <div className="divide-y divide-border rounded-xl border border-border bg-surface">
      {applications.map((a) => (
        <Link
          key={a.application_id}
          href={`/candidate/applications/${a.application_id}`}
          className="flex items-center justify-between gap-3 p-4 transition-colors hover:bg-surface-hover"
        >
          <div>
            <p className="font-medium">{a.vacancy_title ?? "Vacancy"}</p>
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

export default function MyApplicationsPage() {
  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">My applications</h1>
        <p className="mt-1 text-sm text-muted">Track the status of the roles you&apos;ve applied to.</p>
      </div>
      <ApplicationsList />
    </PortalGuard>
  );
}
