"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { StatusBadge } from "@/components/status";
import { ListSkeleton } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import type { ApplicationDetail, ApplicationStatus } from "@/lib/types";

const STATUS_FILTERS: Array<{ label: string; value: ApplicationStatus | "ALL" }> = [
  { label: "All", value: "ALL" },
  { label: "Applied", value: "APPLIED" },
  { label: "Shortlisted", value: "SHORTLISTED" },
  { label: "Rejected", value: "REJECTED" },
];

export default function ManagerAllApplicationsPage() {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "ALL">("ALL");

  useEffect(() => {
    api
      .allApplications()
      .then(setApplications)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load applications."));
  }, []);

  const filtered = useMemo(() => {
    if (!applications) return [];
    const q = search.toLowerCase();
    return applications.filter((a) => {
      const matchesStatus = statusFilter === "ALL" || a.application_status === statusFilter;
      const matchesSearch =
        !q ||
        (a.candidate_name ?? "").toLowerCase().includes(q) ||
        (a.candidate_email ?? "").toLowerCase().includes(q) ||
        (a.vacancy_title ?? "").toLowerCase().includes(q);
      return matchesStatus && matchesSearch;
    });
  }, [applications, search, statusFilter]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Applications</h1>
        <p className="mt-0.5 text-sm text-gray-500">
          Every application across all vacancies, in one place.
        </p>
      </div>

      <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search by candidate or vacancy…"
            className="input pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-1.5 overflow-x-auto">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                statusFilter === f.value
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {!error && applications === null && <ListSkeleton rows={6} />}

      {applications !== null && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-sky-100 bg-sky-50">
                <tr>
                  <th className="table-th">Candidate</th>
                  <th className="table-th hidden md:table-cell">Vacancy</th>
                  <th className="table-th hidden sm:table-cell">Match Score</th>
                  <th className="table-th hidden sm:table-cell">Applied</th>
                  <th className="table-th">Status</th>
                  <th className="table-th">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.length ? (
                  filtered.map((a) => (
                    <tr key={a.application_id} className="transition-colors hover:bg-sky-50">
                      <td className="table-td">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-600">
                            {(a.candidate_name ?? a.candidate_email ?? "?").charAt(0).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="truncate font-medium text-gray-900">
                              {a.candidate_name ?? a.candidate_email}
                            </p>
                            <p className="truncate text-xs text-gray-500 md:hidden">{a.vacancy_title}</p>
                          </div>
                        </div>
                      </td>
                      <td className="table-td hidden md:table-cell">{a.vacancy_title ?? "—"}</td>
                      <td className="table-td hidden sm:table-cell">
                        {a.evaluated && a.evaluation ? (
                          <span className="font-medium text-gray-900">{a.evaluation.score}</span>
                        ) : (
                          <span className="text-xs text-gray-400">screening…</span>
                        )}
                      </td>
                      <td className="table-td hidden text-xs text-gray-500 sm:table-cell">
                        {new Date(a.applied_at).toLocaleDateString()}
                      </td>
                      <td className="table-td">
                        <StatusBadge status={a.application_status} />
                      </td>
                      <td className="table-td">
                        <Link
                          href={`/manager/applications/${a.application_id}`}
                          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
                        >
                          View
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </Link>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="py-16 text-center">
                      <div className="text-gray-400">
                        <svg className="mx-auto mb-3 h-12 w-12 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <p className="text-sm">No applications found</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
