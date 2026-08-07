"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { Modal } from "@/components/modal";
import { api, ApiError } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

const EMPLOYMENT_TYPES = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP"];

const emptyForm = {
  title: "",
  departmentName: "",
  description: "",
  employmentType: "FULL_TIME",
  openingDate: "",
  closingDate: "",
};

function VacanciesTable({
  vacancies,
  loading,
  search,
}: {
  vacancies: Vacancy[];
  loading: boolean;
  search: string;
}) {
  const filtered = vacancies.filter(
    (v) =>
      v.title.toLowerCase().includes(search.toLowerCase()) ||
      (v.department_name ?? "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-sky-100 bg-sky-50">
            <tr>
              <th className="table-th">Title</th>
              <th className="table-th hidden md:table-cell">Department</th>
              <th className="table-th hidden sm:table-cell">Type</th>
              <th className="table-th hidden sm:table-cell">Posted</th>
              <th className="table-th">Status</th>
              <th className="table-th">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="table-td py-8 text-center text-gray-500">
                  Loading…
                </td>
              </tr>
            ) : filtered.length ? (
              filtered.map((v) => (
                <tr key={v.vacancy_id} className="transition-colors hover:bg-sky-50">
                  <td className="table-td">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-100 text-sm font-semibold text-blue-600">
                        {v.title.charAt(0)}
                      </div>
                      <p className="font-medium text-gray-900">{v.title}</p>
                    </div>
                  </td>
                  <td className="table-td hidden md:table-cell">{v.department_name ?? "—"}</td>
                  <td className="table-td hidden sm:table-cell">
                    <span className="badge bg-gray-100 text-gray-600">
                      {v.employment_type.replaceAll("_", " ")}
                    </span>
                  </td>
                  <td className="table-td hidden text-xs text-gray-500 sm:table-cell">
                    {new Date(v.created_at).toLocaleDateString()}
                  </td>
                  <td className="table-td">
                    <StatusBadge status={v.status} />
                  </td>
                  <td className="table-td">
                    <Link
                      href={`/manager/vacancies/${v.vacancy_id}`}
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
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M20 7h-4V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2zm-6 0h-4V5h4v2z" />
                    </svg>
                    <p className="text-sm">No vacancies found</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
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
  const [vacancies, setVacancies] = useState<Vacancy[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
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
      setModalOpen(false);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to create vacancy.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Vacancies</h1>
            <p className="mt-0.5 text-sm text-gray-500">{vacancies.length} vacancies, open and closed</p>
          </div>
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
            <span className="hidden sm:inline">Post a Vacancy</span>
          </button>
        </div>

        <div className="card p-4">
          <div className="relative">
            <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search by title or department…"
              className="input pl-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        <VacanciesTable vacancies={vacancies} loading={loading} search={search} />
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
    </PortalGuard>
  );
}
