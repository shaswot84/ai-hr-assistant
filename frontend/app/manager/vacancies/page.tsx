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
import type { KeywordTier, ScoringKeyword, Vacancy } from "@/lib/types";

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

/** A generated keyword plus whether the manager kept it — the checkbox
 * decides inclusion, the tier decides its weight (fixed critical=5,
 * important=3, nice_to_have=1 mapping applied server-side at scoring time). */
type EditableKeyword = ScoringKeyword & { checked: boolean };

const TIER_ORDER: KeywordTier[] = ["critical", "important", "nice_to_have"];
const TIER_LABELS: Record<KeywordTier, string> = {
  critical: "Critical",
  important: "Important",
  nice_to_have: "Nice to have",
};
const TIER_ACTIVE_STYLES: Record<KeywordTier, string> = {
  critical: "bg-red-600 text-white",
  important: "bg-amber-500 text-white",
  nice_to_have: "bg-zinc-500 text-white",
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
  const [keywords, setKeywords] = useState<EditableKeyword[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

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

  const checkedKeywordCount = keywords.filter((k) => k.checked).length;

  async function handleGenerateKeywords() {
    setGenerateError(null);
    setGenerating(true);
    try {
      const result = await api.suggestKeywords(form.title, form.description);
      setKeywords(result.keywords.map((kw) => ({ ...kw, checked: true })));
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.detail : "Failed to generate keywords.");
    } finally {
      setGenerating(false);
    }
  }

  function toggleKeyword(index: number) {
    setKeywords((prev) => prev.map((kw, i) => (i === index ? { ...kw, checked: !kw.checked } : kw)));
  }

  function setKeywordTier(index: number, tier: KeywordTier) {
    setKeywords((prev) => prev.map((kw, i) => (i === index ? { ...kw, tier } : kw)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (checkedKeywordCount === 0) {
      setError("Keep at least one scoring keyword — it's what applications get ranked against.");
      return;
    }
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
        scoring_keywords: keywords
          .filter((k) => k.checked)
          .map(({ keyword, tier }) => ({ keyword, tier })),
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

  function openCreateModal() {
    setForm(emptyForm);
    setKeywords([]);
    setGenerateError(null);
    setError(null);
    setModalOpen(true);
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
              onClick={openCreateModal}
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
                  <button type="button" className="btn-primary" onClick={openCreateModal}>
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

            <div className="col-span-2">
              <div className="flex items-center justify-between">
                <label className="label mb-0">Scoring Keywords *</label>
                <button
                  type="button"
                  disabled={generating || !form.title.trim()}
                  onClick={handleGenerateKeywords}
                  className="btn-secondary text-xs"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
                    />
                  </svg>
                  {generating ? "Generating…" : keywords.length ? "Regenerate" : "Generate Weighted Keywords"}
                </button>
              </div>
              <p className="mt-1 text-xs text-zinc-400">
                Applications will be ranked against these — uncheck any that don&apos;t belong, and set how
                much each one should count.
              </p>

              {generateError && <p className="mt-2 text-sm text-red-600">{generateError}</p>}

              {keywords.length > 0 && (
                <div className="mt-3 divide-y divide-zinc-100 rounded-lg border border-zinc-200">
                  {keywords.map((kw, i) => (
                    <div key={`${kw.keyword}-${i}`} className="flex items-center gap-3 px-3 py-2">
                      <input
                        type="checkbox"
                        checked={kw.checked}
                        onChange={() => toggleKeyword(i)}
                        className="h-4 w-4 shrink-0 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span
                        className={`flex-1 truncate text-sm ${kw.checked ? "text-zinc-900" : "text-zinc-400 line-through"}`}
                      >
                        {kw.keyword}
                      </span>
                      <div className="flex shrink-0 gap-1 rounded-md bg-zinc-100 p-0.5">
                        {TIER_ORDER.map((tier) => (
                          <button
                            key={tier}
                            type="button"
                            disabled={!kw.checked}
                            onClick={() => setKeywordTier(i, tier)}
                            className={`rounded px-2 py-1 text-[11px] font-medium transition-colors disabled:opacity-40 ${
                              kw.tier === tier ? TIER_ACTIVE_STYLES[tier] : "text-zinc-500 hover:bg-zinc-200"
                            }`}
                          >
                            {TIER_LABELS[tier]}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
            <button
              type="submit"
              disabled={submitting || checkedKeywordCount === 0}
              title={checkedKeywordCount === 0 ? "Generate and keep at least one scoring keyword first" : undefined}
              className="btn-primary"
            >
              {submitting ? "Creating…" : "Create Vacancy"}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}
