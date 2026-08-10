"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { api, ApiError } from "@/lib/api";
import type { ApplicationStatusView } from "@/lib/types";

function ApplicationsList() {
  const [applications, setApplications] = useState<ApplicationStatusView[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myApplications()
      .then(setApplications)
      .catch((err) =>
        setError(err instanceof ApiError ? err.detail : "Failed to load applications.")
      );
  }, []);

  if (error) return <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>;
  if (applications === null) return <ListSkeleton />;
  if (applications.length === 0)
    return (
      <div className="card">
        <EmptyState
          title="You haven't applied yet"
          description="Applications you submit will show up here so you can track their status."
          action={
            <Link href="/candidate" className="btn-primary">
              Browse vacancies
            </Link>
          }
        />
      </div>
    );

  return (
    <div className="card overflow-hidden">
      <div className="table-scroll">
        <table className="w-full">
          <thead className="bg-zinc-50">
            <tr>
              <th className="table-th">Role</th>
              <th className="table-th">Applied</th>
              <th className="table-th">Status</th>
              <th className="table-th text-right">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {applications.map((a) => (
              <tr key={a.application_id} className="table-row">
                <td className="table-td">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-[13px] font-semibold text-blue-600">
                      {(a.vacancy_title ?? "?").charAt(0)}
                    </div>
                    <p className="font-medium text-zinc-900">{a.vacancy_title ?? "Vacancy"}</p>
                  </div>
                </td>
                <td className="table-td text-xs text-zinc-500">
                  {new Date(a.applied_at).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })}
                </td>
                <td className="table-td">
                  <StatusBadge status={a.application_status} />
                </td>
                <td className="table-td text-right">
                  <Link
                    href={`/candidate/applications/${a.application_id}`}
                    className="link inline-flex items-center gap-1"
                  >
                    View
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function MyApplicationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="My Applications"
        description="Track the status of the roles you've applied to."
      />
      <ApplicationsList />
    </div>
  );
}
