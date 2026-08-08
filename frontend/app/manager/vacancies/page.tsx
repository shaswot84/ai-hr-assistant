"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { Modal } from "@/components/modal";
import { ListSkeleton } from "@/components/loading";
import { EmptyState } from "@/components/empty-state";
import { Pagination } from "@/components/pagination";
import { SortableTh, Th, toggleSort, type SortState } from "@/components/table";
import { useToast } from "@/components/toast";
import { api, ApiError } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

const EMPLOYMENT_TYPES = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP"];
const PAGE_SIZE = 8;

const emptyForm = {
  title: "",
  departmentName: "",
  description: "",
  employmentType: "FULL_TIME",
  openingDate: "",
  closingDate: "",
};

function sortVacancies(list: Vacancy[], sort: SortState): Vacancy[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const sorted = [...list];
  switch (sort.key) {
    case "title":
      sorted.sort((a, b) => a.title.localeCompare(b.title) * dir);
      break;
    case "department":
      sorted.sort((a, b) => (a.department_name ?? "").localeCompare(b.department_name ?? "") * dir);
      break;
    case "posted":
      sorted.sort((a, b) => (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) * dir);
      break;
    case "status":
      sorted.sort((a, b) => a.status.localeCompare(b.status) * dir);
      break;
  }
  return sorted;
}

export default function ManagerVacanciesPage() {
  return (
    <Suspense fallback={null}>
      <ManagerVacanciesContent />
    </Suspense>
  );
}

function ManagerVacanciesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { addToast } = useToast();
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "posted", dir: "desc" });
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(() => searchParams.get("new") === "1");
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useMemo(
    () => () =>
      api
        .listVacancies()
        .then(setVacancies)
        .catch(() => setVacancies([]))
        .finally(() => setLoading(false)),
    []
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    // Clean the ?new=1 URL param the initial modalOpen state read from —
    // a router call, not React state, so it doesn't trigger the
    // set-state-in-effect lint rule.
    if (searchParams.get("new") === "1") {
      router.replace("/manager/vacancies");
    }
  }, [searchParams, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createVacancy({
        title: form.title,
        department_name: form.departmentName,
        description: form.description || null,
        employment_type: form.employmentType,
        opening_date: form.openingDate || null,
        closing_date: form.closingDate || null,
      });
      addToast("Vacancy posted successfully.", "success");
      setModalOpen(false);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to create vacancy.");
    } finally {
      setSubmitting(false);
    }
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const searched = vacancies.filter(
      (v) =>
        v.title.toLowerCase().includes(q) ||
        (v.department_name ?? "").toLowerCase().includes(q)
    );
    return sortVacancies(searched, sort);
  }, [vacancies, search, sort]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount);
  const pageRows = filtered.slice((curPage - 1) * PAGE_SIZE, curPage * PAGE_SIZE);

  function handleSort(key: string) {
    setSort((s) => toggleSort(s, key));
    setPage(1);
  }

  return (
    <>
      <div className="space-y-6">
        <PageHeader
          title="Vacancies"
          description={`${vacancies.length} roles · open, closed, and archived`}
          actions={
            <button
              type="button"
              onClick={() => {
                setForm(emptyForm);
                setModalOpen(true);
              }}
              className="btn-primary"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Post a Vacancy
            </button>
          }
        />

        {/* Controls */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
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
              placeholder="Search by title or department…"
              className="input pl-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>

        {loading ? (
          <ListSkeleton rows={5} />
        ) : filtered.length === 0 ? (
          <div className="card">
            <EmptyState
              title={search ? "No matching vacancies" : "No vacancies yet"}
              description={
                search
                  ? "Nothing matches your search. Try a different title or department."
                  : "Post your first vacancy to start receiving applications."
              }
              action={
                !search ? (
                  <button type="button" className="btn-primary" onClick={() => setModalOpen(true)}>
                    Post a Vacancy
                  </button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="card overflow-hidden">
            <div className="table-scroll max-h-[560px]">
              <table className="w-full">
                <thead className="bg-zinc-50">
                  <tr className="group">
                    <SortableTh sortKey="title" sort={sort} onSort={handleSort}>
                      Title
                    </SortableTh>
                    <SortableTh sortKey="department" sort={sort} onSort={handleSort} className="hidden md:table-cell">
                      Department
                    </SortableTh>
                    <Th className="hidden sm:table-cell">Type</Th>
                    <SortableTh sortKey="posted" sort={sort} onSort={handleSort} className="hidden sm:table-cell">
                      Posted
                    </SortableTh>
                    <SortableTh sortKey="status" sort={sort} onSort={handleSort}>
                      Status
                    </SortableTh>
                    <Th className="text-right">Actions</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {pageRows.map((v) => (
                    <tr key={v.vacancy_id} className="table-row">
                      <td className="table-td">
                        <div className="flex items-center gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-sm font-semibold text-blue-600">
                            {v.title.charAt(0)}
                          </div>
                          <p className="font-medium text-zinc-900">{v.title}</p>
                        </div>
                      </td>
                      <td className="table-td hidden text-zinc-500 md:table-cell">
                        {v.department_name ?? "—"}
                      </td>
                      <td className="table-td hidden sm:table-cell">
                        <span className="badge bg-zinc-100 text-zinc-600">
                          {v.employment_type.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className="table-td hidden text-xs text-zinc-500 sm:table-cell">
                        {new Date(v.created_at).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </td>
                      <td className="table-td">
                        <StatusBadge status={v.status} />
                      </td>
                      <td className="table-td text-right">
                        <Link
                          href={`/manager/vacancies/${v.vacancy_id}`}
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
            <Pagination page={curPage} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
          </div>
        )}
      </div>

      <Modal isOpen={modalOpen} onClose={() => setModalOpen(false)} title="Post a Vacancy" size="lg">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">Title *</label>
              <input
                required
                className="input"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="Senior Backend Engineer"
              />
            </div>
            <div>
              <label className="label">Department *</label>
              <input
                required
                className="input"
                value={form.departmentName}
                onChange={(e) => setForm({ ...form, departmentName: e.target.value })}
                placeholder="Engineering"
              />
            </div>
            <div>
              <label className="label">Employment Type</label>
              <select
                className="input"
                value={form.employmentType}
                onChange={(e) => setForm({ ...form, employmentType: e.target.value })}
              >
                {EMPLOYMENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className="label">Description</label>
              <textarea
                className="input"
                rows={5}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="Responsibilities, requirements, and what makes this role a good fit…"
              />
            </div>
            <div>
              <label className="label">Opening Date</label>
              <input
                type="date"
                className="input"
                value={form.openingDate}
                onChange={(e) => setForm({ ...form, openingDate: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Closing Date</label>
              <input
                type="date"
                className="input"
                value={form.closingDate}
                onChange={(e) => setForm({ ...form, closingDate: e.target.value })}
              />
            </div>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={() => setModalOpen(false)} className="btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Creating…" : "Create Vacancy"}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}
