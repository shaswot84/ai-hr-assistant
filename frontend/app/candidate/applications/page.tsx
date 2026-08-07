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
  if (applications === null) return <p className="text-sm text-gray-500">Loading…</p>;
  if (applications.length === 0)
    return (
      <div className="card p-10 text-center">
        <p className="text-sm text-gray-500">You haven&apos;t applied to any vacancies yet.</p>
      </div>
    );

  return (
    <div className="card divide-y divide-gray-100 overflow-hidden">
      {applications.map((a) => (
        <Link
          key={a.application_id}
          href={`/candidate/applications/${a.application_id}`}
          className="flex items-center gap-3 px-6 py-4 transition-colors hover:bg-sky-50"
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-100 text-sm font-semibold text-blue-600">
            {(a.vacancy_title ?? "?").charAt(0)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-gray-900">{a.vacancy_title ?? "Vacancy"}</p>
            <p className="mt-0.5 text-xs text-gray-500">
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
      <div className="animate-fade-in space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">My Applications</h1>
          <p className="mt-1 text-sm text-gray-500">Track the status of the roles you&apos;ve applied to.</p>
        </div>
        <ApplicationsList />
      </div>
    </PortalGuard>
  );
}
