"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { api } from "@/lib/api";

const EMPLOYMENT_TYPES = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP"];

export default function CreateVacancyPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    title: "",
    department_name: "",
    description: "",
    employment_type: "FULL_TIME",
    opening_date: "",
    closing_date: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function submit() {
    if (!form.title.trim() || !form.department_name.trim()) {
      setError("Title and department are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const vacancy = await api.createVacancy({
        title: form.title.trim(),
        department_name: form.department_name.trim(),
        description: form.description.trim() || null,
        employment_type: form.employment_type,
        opening_date: form.opening_date || null,
        closing_date: form.closing_date || null,
      });
      router.push(`/manager/vacancies/${vacancy.vacancy_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create vacancy");
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition-colors focus:border-border-strong";

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in mx-auto max-w-2xl">
        <h1 className="text-xl font-semibold tracking-tight">Create vacancy</h1>
        <p className="mt-1 text-sm text-muted">Post a new opening for candidates to apply to.</p>

        <div className="mt-6 space-y-4 rounded-xl border border-border bg-surface p-6">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="title">
              Title
            </label>
            <input
              id="title"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              className={inputClass}
              placeholder="Backend Engineer"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="dept">
                Department
              </label>
              <input
                id="dept"
                value={form.department_name}
                onChange={(e) => set("department_name", e.target.value)}
                className={inputClass}
                placeholder="Engineering"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="type">
                Employment type
              </label>
              <select
                id="type"
                value={form.employment_type}
                onChange={(e) => set("employment_type", e.target.value)}
                className={inputClass}
              >
                {EMPLOYMENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace("_", " ")}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="desc">
              Description
            </label>
            <textarea
              id="desc"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              rows={6}
              className={`${inputClass} resize-y`}
              placeholder="Responsibilities, requirements, and what you are looking for."
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="open">
                Opening date
              </label>
              <input
                id="open"
                type="date"
                value={form.opening_date}
                onChange={(e) => set("opening_date", e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="close">
                Closing date
              </label>
              <input
                id="close"
                type="date"
                value={form.closing_date}
                onChange={(e) => set("closing_date", e.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          {error && <p className="text-sm text-danger">{error}</p>}

          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="w-full rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Creating…" : "Create vacancy"}
          </button>
        </div>
      </div>
    </PortalGuard>
  );
}