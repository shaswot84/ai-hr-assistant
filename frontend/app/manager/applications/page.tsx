"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { Pagination } from "@/components/pagination";
import { SortableTh, Th, toggleSort, type SortState } from "@/components/table";
import { Modal } from "@/components/modal";
import { HireModal } from "@/components/hire-modal";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import { DOES_NOT_MEET_REQUIREMENTS } from "@/lib/types";
import type { ApplicationDetail, ApplicationStatus } from "@/lib/types";

const PAGE_SIZE = 8;

const STATUS_FILTERS: Array<{ label: string; value: ApplicationStatus | "ALL" }> = [
  { label: "All", value: "ALL" },
  { label: "Applied", value: "APPLIED" },
  { label: "Shortlisted", value: "SHORTLISTED" },
  { label: "Rejected", value: "REJECTED" },
  { label: "Withdrawn", value: "WITHDRAWN" },
];

const RECOMMENDATION_TONE: Record<string, string> = {
  "Strong Match": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Good Match": "bg-blue-50 text-blue-700 ring-blue-600/20",
  "Possible Match": "bg-amber-50 text-amber-700 ring-amber-600/20",
  "Weak Match": "bg-red-50 text-red-700 ring-red-600/20",
};

/** Ordinal rank for sorting by fit — there's no numeric score anymore, so
 * "Match" sorts by the categorical recommendation (worst to best), with
 * failed/in-progress screenings ranked below any real result. */
const RECOMMENDATION_RANK: Record<string, number> = {
  [DOES_NOT_MEET_REQUIREMENTS]: 0,
  "Weak Match": 1,
  "Possible Match": 2,
  "Good Match": 3,
  "Strong Match": 4,
};

function matchRank(a: ApplicationDetail): number {
  if (!a.evaluated || !a.evaluation || a.evaluation.failed) return -1;
  const recommendation = a.evaluation.detail?.recommendation ?? "";
  return RECOMMENDATION_RANK[recommendation] ?? -1;
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
    case "match":
      sorted.sort((a, b) => (matchRank(a) - matchRank(b)) * dir);
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
  const [rejecting, setRejecting] = useState<ApplicationDetail | null>(null);
  const [rejectBusy, setRejectBusy] = useState(false);
  const [hireTarget, setHireTarget] = useState<ApplicationDetail | null>(null);
  const { addToast } = useToast();

  const refresh = useMemo(
    () => () =>
      api
        .allApplications()
        .then(setApplications)
        .catch((err) => setError(err instanceof ApiError ? err.detail : "Failed to load applications.")),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  /** Reject an APPLIED application inline from the list (terminal, emails the candidate). */
  async function handleReject() {
    if (!rejecting) return;
    setRejectBusy(true);
    try {
      await api.decide(rejecting.application_id, "reject");
      addToast(`${rejecting.candidate_name ?? "Application"} rejected.`, "success");
      setRejecting(null);
      await refresh();
    } catch (err) {
      addToast(err instanceof ApiError ? err.detail : "Failed to reject application.", "error");
      setRejecting(null);
    } finally {
      setRejectBusy(false);
    }
  }

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
                      <SortableTh sortKey="match" sort={sort} onSort={handleSort} align="right" className="hidden sm:table-cell">
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
                          {!a.evaluated || !a.evaluation ? (
                            <span className="text-xs text-zinc-400">screening…</span>
                          ) : a.evaluation.failed ? (
                            <span
                              className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20"
                              title={a.evaluation.overview}
                            >
                              Failed
                            </span>
                          ) : a.evaluation.detail && !a.evaluation.detail.requirements_met ? (
                            <span className="badge bg-red-100 text-red-800 ring-1 ring-inset ring-red-600/30">
                              Doesn&apos;t meet reqs
                            </span>
                          ) : (
                            <span
                              className={`badge ring-1 ring-inset ${RECOMMENDATION_TONE[a.evaluation.detail?.recommendation ?? ""] ?? "bg-zinc-100 text-zinc-600 ring-zinc-500/20"}`}
                            >
                              {a.evaluation.detail?.recommendation ?? "Reviewed"}
                            </span>
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
                          <div className="flex flex-wrap items-center gap-1.5">
                            <StatusBadge status={a.application_status} />
                            {a.hired && (
                              <span className="badge bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                                Hired
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="table-td text-right">
                          <div className="inline-flex items-center gap-3">
                            {a.application_status === "APPLIED" && (
                              <button
                                type="button"
                                className="link text-red-600 hover:text-red-700"
                                onClick={() => setRejecting(a)}
                              >
                                Reject
                              </button>
                            )}
                            {a.application_status === "SHORTLISTED" && !a.hired && (
                              <button
                                type="button"
                                className="link text-emerald-600 hover:text-emerald-700"
                                onClick={() => setHireTarget(a)}
                              >
                                Hire
                              </button>
                            )}
                            <Link
                              href={`/manager/applications/${a.application_id}`}
                              className="link inline-flex items-center gap-1"
                            >
                              Review
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                              </svg>
                            </Link>
                          </div>
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

      {/* Reject confirmation (inline on APPLIED rows) */}
      {rejecting && (
        <Modal isOpen onClose={() => !rejectBusy && setRejecting(null)} title="Reject this application?" size="sm">
          <div className="space-y-4">
            <p className="text-sm leading-relaxed text-zinc-600">
              <span className="font-medium text-zinc-900">
                {rejecting.candidate_name ?? rejecting.candidate_email}
              </span>{" "}
              will be emailed that their application for{" "}
              <span className="font-medium text-zinc-900">{rejecting.vacancy_title ?? "this role"}</span>{" "}
              wasn&apos;t selected. This decision can&apos;t be changed afterwards.
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn-secondary"
                disabled={rejectBusy}
                onClick={() => setRejecting(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary bg-red-600 hover:bg-red-700"
                disabled={rejectBusy}
                onClick={handleReject}
              >
                {rejectBusy ? "Rejecting…" : "Reject"}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Hire handoff (inline on SHORTLISTED rows) */}
      {hireTarget && (
        <HireModal
          applicationId={hireTarget.application_id}
          candidateName={hireTarget.candidate_name ?? hireTarget.candidate_email ?? "Candidate"}
          onClose={() => setHireTarget(null)}
          onHired={(employee) => {
            setHireTarget(null);
            addToast(
              `${hireTarget.candidate_name ?? "Candidate"} hired as ${employee.first_name} ${employee.last_name} — other applications withdrawn.`,
              "success"
            );
            refresh();
          }}
        />
      )}
    </div>
  );
}
