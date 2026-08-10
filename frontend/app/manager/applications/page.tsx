"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { Pagination } from "@/components/pagination";
import { SortableTh, Th, toggleSort, type SortState } from "@/components/table";
import { api, ApiError } from "@/lib/api";
import type { ApplicationDetail, ApplicationStatus } from "@/lib/types";

const PAGE_SIZE = 8;

const STATUS_FILTERS: Array<{ label: string; value: ApplicationStatus | "ALL" }> = [
  { label: "All", value: "ALL" },
  { label: "Applied", value: "APPLIED" },
  { label: "Shortlisted", value: "SHORTLISTED" },
  { label: "Rejected", value: "REJECTED" },
];

function scoreTone(score: number) {
  if (score >= 70) return "bg-emerald-50 text-emerald-700";
  if (score >= 40) return "bg-amber-50 text-amber-700";
  return "bg-red-50 text-red-700";
}

function sortApplications(list: ApplicationDetail[], sort: SortState): ApplicationDetail[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const sorted = [...list];
  switch (sort.key) {
    case "candidate":
      sorted.sort((a, b) =>
        (a.candidate_name ?? a.candidate_email ?? "").localeCompare(
          b.candidate_name ?? b.candidate_email ?? ""
        ) * dir
      );
      break;
    case "vacancy":
      sorted.sort((a, b) => (a.vacancy_title ?? "").localeCompare(b.vacancy_title ?? "") * dir);
      break;
    case "score":
      sorted.sort((a, b) => {
        const av = a.evaluated && a.evaluation ? a.evaluation.score : -1;
        const bv = b.evaluated && b.evaluation ? b.evaluation.score : -1;
        return (av - bv) * dir;
      });
      break;
    case "applied":
      sorted.sort((a, b) => (new Date(a.applied_at).getTime() - new Date(b.applied_at).getTime()) * dir);
      break;
    case "status":
      sorted.sort((a, b) => a.application_status.localeCompare(b.application_status) * dir);
      break;
  }
  return sorted;
}

export default function ManagerAllApplicationsPage() {
  const [applications, setApplications] = useState<ApplicationDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "ALL">("ALL");
  const [sort, setSort] = useState<SortState>({ key: "applied", dir: "desc" });
  const [page, setPage] = useState(1);

  useEffect(() => {
    api
      .allApplications()
      .then(setApplications)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load applications."));
  }, []);

  const filtered = useMemo(() => {
    if (!applications) return [];
    const q = search.toLowerCase();
    const searched = applications.filter((a) => {
      const matchesStatus = statusFilter === "ALL" || a.application_status === statusFilter;
      const matchesSearch =
        !q ||
        (a.candidate_name ?? "").toLowerCase().includes(q) ||
        (a.candidate_email ?? "").toLowerCase().includes(q) ||
        (a.vacancy_title ?? "").toLowerCase().includes(q);
      return matchesStatus && matchesSearch;
    });
    return sortApplications(searched, sort);
  }, [applications, search, statusFilter, sort]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount);
  const pageRows = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);
  const countByStatus = useMemo(() => {
    if (!applications) return new Map<string, number>();
    const m = new Map<string, number>();
    for (const a of applications) m.set(a.application_status, (m.get(a.application_status) ?? 0) + 1);
    return m;
  }, [applications]);

  function handleSort(key: string) {
    setSort((s) => toggleSort(s, key));
    setPage(1);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Applications"
        description="Every application across all vacancies, in one place."
        meta={
          applications && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="badge bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20">
                {applications.length} total
              </span>
              <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                {countByStatus.get("SHORTLISTED") ?? 0} shortlisted
              </span>
            </div>
          )
        }
      />

      {/* Controls */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            placeholder="Search by candidate or vacancy…"
            className="input pl-9"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="flex gap-1 overflow-x-auto rounded-lg border border-zinc-200 bg-white p-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => {
                setStatusFilter(f.value);
                setPage(1);
              }}
              className={`tab ${statusFilter === f.value ? "tab-active" : ""}`}
            >
              {f.label}
              {f.value !== "ALL" && (
                <span className="tabular-nums text-zinc-400">
                  {countByStatus.get(f.value) ?? 0}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && applications === null && <ListSkeleton rows={6} />}

      {applications !== null && (
        <>
          {filtered.length === 0 ? (
            <div className="card">
              <EmptyState
                title={search || statusFilter !== "ALL" ? "No matching applications" : "No applications yet"}
                description={
                  search || statusFilter !== "ALL"
                    ? "Nothing matches your filters. Try widening the search."
                    : "Applications will appear here once candidates start applying."
                }
              />
            </div>
          ) : (
            <div className="card overflow-hidden">
              <div className="table-scroll max-h-[560px]">
                <table className="w-full">
                  <thead className="bg-zinc-50">
                    <tr className="group">
                      <SortableTh sortKey="candidate" sort={sort} onSort={handleSort}>
                        Candidate
                      </SortableTh>
                      <SortableTh sortKey="vacancy" sort={sort} onSort={handleSort} className="hidden md:table-cell">
                        Vacancy
                      </SortableTh>
                      <SortableTh sortKey="score" sort={sort} onSort={handleSort} align="right" className="hidden sm:table-cell">
                        Match
                      </SortableTh>
                      <SortableTh sortKey="applied" sort={sort} onSort={handleSort} className="hidden sm:table-cell">
                        Applied
                      </SortableTh>
                      <SortableTh sortKey="status" sort={sort} onSort={handleSort}>
                        Status
                      </SortableTh>
                      <Th align="right">Actions</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {pageRows.map((a) => (
                      <tr key={a.application_id} className="table-row">
                        <td className="table-td">
                          <div className="flex items-center gap-3">
                            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-[13px] font-semibold text-zinc-600">
                              {(a.candidate_name ?? a.candidate_email ?? "?").charAt(0).toUpperCase()}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate font-medium text-zinc-900">
                                {a.candidate_name ?? a.candidate_email}
                              </p>
                              <p className="truncate text-xs text-zinc-400 md:hidden">{a.vacancy_title}</p>
                            </div>
                          </div>
                        </td>
                        <td className="table-td hidden text-zinc-500 md:table-cell">
                          {a.vacancy_title ?? "—"}
                        </td>
                        <td className="table-td hidden text-right sm:table-cell">
                          {a.evaluated && a.evaluation ? (
                            <span
                              className={`badge tabular-nums ${scoreTone(a.evaluation.score)}`}
                            >
                              {a.evaluation.score}
                            </span>
                          ) : (
                            <span className="text-xs text-zinc-400">screening…</span>
                          )}
                        </td>
                        <td className="table-td hidden text-xs text-zinc-500 sm:table-cell">
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
                            href={`/manager/applications/${a.application_id}`}
                            className="link inline-flex items-center gap-1"
                          >
                            Review
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
              <Pagination page={curPage} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
