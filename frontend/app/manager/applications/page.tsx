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
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
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

function scoreTone(score: number) {
  if (score >= 70) return "text-emerald-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

/** A candidate who clearly failed a stated hard requirement — kept in a
 * separate list entirely from everyone else (rather than just sorted
 * below them), so a manager reviewing "who's actually in the running"
 * never has to scan past eliminated candidates to find them. */
function failsRequirements(a: ApplicationDetail): boolean {
  return (
    a.evaluated && !!a.evaluation && !a.evaluation.failed && a.evaluation.detail?.requirements_met === false
  );
}

/** Ranking within a single list: higher weighted keyword score first;
 * unscored/still-screening applications sink to the bottom. Since the two
 * requirement tiers are now separate lists (not interleaved), this only
 * ever needs to rank within one tier at a time. */
function matchQuality(a: ApplicationDetail): number {
  if (!a.evaluated || !a.evaluation || a.evaluation.failed) return -1;
  return a.evaluation.keyword_score ?? 0;
}

/** Shared table for both the "meets requirements" and "doesn't meet
 * requirements" sections — identical columns, just fed a different
 * (already filtered + sorted + paginated) slice of rows. `showReject`
 * controls whether the inline Reject action appears: only the
 * doesn't-meet-requirements table gets it here — deciding on candidates
 * still in the running happens from the full review page, not this list. */
function ApplicationsTable({
  rows,
  total,
  page,
  onPage,
  sort,
  onSort,
  onReject,
  showReject,
}: {
  rows: ApplicationDetail[];
  total: number;
  page: number;
  onPage: (page: number) => void;
  sort: SortState;
  onSort: (key: string) => void;
  onReject: (a: ApplicationDetail) => void;
  showReject: boolean;
}) {
  return (
    <div className="card overflow-hidden">
      <div className="table-scroll max-h-[560px]">
        <table className="w-full">
          <thead className="bg-zinc-50">
            <tr className="group">
              <SortableTh sortKey="candidate" sort={sort} onSort={onSort}>
                Candidate
              </SortableTh>
              <SortableTh sortKey="vacancy" sort={sort} onSort={onSort} className="hidden md:table-cell">
                Vacancy
              </SortableTh>
              <SortableTh sortKey="match" sort={sort} onSort={onSort} align="right" className="hidden sm:table-cell">
                Match
              </SortableTh>
              <SortableTh sortKey="applied" sort={sort} onSort={onSort} className="hidden sm:table-cell">
                Applied
              </SortableTh>
              <SortableTh sortKey="status" sort={sort} onSort={onSort}>
                Status
              </SortableTh>
              <Th align="right">Actions</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {rows.map((a) => (
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
                <td className="table-td hidden text-zinc-500 md:table-cell">{a.vacancy_title ?? "—"}</td>
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
                  ) : a.evaluation.keyword_score !== null ? (
                    <span className={`font-semibold tabular-nums ${scoreTone(a.evaluation.keyword_score)}`}>
                      {a.evaluation.keyword_score}%
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
                    {showReject && a.application_status === "APPLIED" && (
                      <button
                        type="button"
                        className="link text-red-600 hover:text-red-700"
                        onClick={() => onReject(a)}
                      >
                        Reject
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
      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPage={onPage} />
    </div>
  );
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
      sorted.sort((a, b) => (matchQuality(a) - matchQuality(b)) * dir);
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
  const [sort, setSort] = useState<SortState>({ key: "match", dir: "desc" });
  const [page, setPage] = useState(1);
  const [failedPage, setFailedPage] = useState(1);
  const [failedExpanded, setFailedExpanded] = useState(false);
  const [rejecting, setRejecting] = useState<ApplicationDetail | null>(null);
  const [rejectBusy, setRejectBusy] = useState(false);
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

  const searched = useMemo(() => {
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

  // Requirements-failed candidates are a separate list entirely, not just
  // sorted below everyone else — a manager scanning who's still in the
  // running shouldn't have to look past eliminated candidates to find them.
  const filtered = useMemo(
    () => sortApplications(searched.filter((a) => !failsRequirements(a)), sort),
    [searched, sort]
  );
  const failedFiltered = useMemo(
    () => sortApplications(searched.filter(failsRequirements), sort),
    [searched, sort]
  );

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount);
  const pageRows = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);

  const failedPageCount = Math.max(1, Math.ceil(failedFiltered.length / PAGE_SIZE));
  const curFailedPage = Math.min(failedPage, failedPageCount);
  const failedPageRows = failedFiltered.slice((curFailedPage - 1) * PAGE_SIZE, curFailedPage * PAGE_SIZE);

  const countByStatus = useMemo(() => {
    if (!applications) return new Map<string, number>();
    const m = new Map<string, number>();
    for (const a of applications) m.set(a.application_status, (m.get(a.application_status) ?? 0) + 1);
    return m;
  }, [applications]);

  function handleSort(key: string) {
    setSort((s) => toggleSort(s, key));
    setPage(1);
    setFailedPage(1);
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
              setFailedPage(1);
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
                setFailedPage(1);
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
          {filtered.length === 0 && failedFiltered.length === 0 ? (
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
            <>
              {filtered.length > 0 && (
                <ApplicationsTable
                  rows={pageRows}
                  total={filtered.length}
                  page={curPage}
                  onPage={setPage}
                  sort={sort}
                  onSort={handleSort}
                  onReject={setRejecting}
                  showReject={false}
                />
              )}

              {/* Kept as a fully separate, collapsed-by-default section (not
                  just sorted below) — a manager scanning who's still in the
                  running for a role shouldn't have to look past eliminated
                  candidates to find them. */}
              {failedFiltered.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setFailedExpanded((v) => !v)}
                    className="mb-3 flex w-full items-center gap-2 text-left"
                    aria-expanded={failedExpanded}
                  >
                    <svg
                      className={`h-4 w-4 shrink-0 text-zinc-400 transition-transform ${failedExpanded ? "rotate-90" : ""}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                    <h2 className="text-sm font-semibold text-red-800">Doesn&apos;t Meet Requirements</h2>
                    <span className="badge bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20">
                      {failedFiltered.length}
                    </span>
                  </button>
                  {failedExpanded && (
                    <ApplicationsTable
                      rows={failedPageRows}
                      total={failedFiltered.length}
                      page={curFailedPage}
                      onPage={setFailedPage}
                      sort={sort}
                      onSort={handleSort}
                      onReject={setRejecting}
                      showReject={true}
                    />
                  )}
                </div>
              )}
            </>
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
    </div>
  );
}
