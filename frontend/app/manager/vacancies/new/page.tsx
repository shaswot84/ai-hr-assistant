"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { api, ApiError } from "@/lib/api";

const EMPLOYMENT_TYPES = ["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP"];

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground";

export default function NewVacancyPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [departmentName, setDepartmentName] = useState("");
  const [description, setDescription] = useState("");
  const [employmentType, setEmploymentType] = useState("FULL_TIME");
  const [openingDate, setOpeningDate] = useState("");
  const [closingDate, setClosingDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const vacancy = await api.createVacancy({
        title,
        department_name: departmentName,
        description: description || null,
        employment_type: employmentType,
        opening_date: openingDate || null,
        closing_date: closingDate || null,
      });
      router.push(`/manager/vacancies/${vacancy.vacancy_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to create vacancy.");
      setSubmitting(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">Post a vacancy</h1>
      </div>

      <form
        onSubmit={handleSubmit}
        className="max-w-xl space-y-4 rounded-xl border border-border bg-surface p-6"
      >
        <Field label="Title">
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputClass}
            placeholder="Senior Backend Engineer"
          />
        </Field>

        <Field label="Department">
          <input
            required
            value={departmentName}
            onChange={(e) => setDepartmentName(e.target.value)}
            className={inputClass}
            placeholder="Engineering"
          />
        </Field>

        <Field label="Employment type">
          <select
            value={employmentType}
            onChange={(e) => setEmploymentType(e.target.value)}
            className={inputClass}
          >
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Description">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={6}
            className={inputClass}
            placeholder="Responsibilities, requirements, and what makes this role a good fit…"
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Opening date">
            <input
              type="date"
              value={openingDate}
              onChange={(e) => setOpeningDate(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Closing date">
            <input
              type="date"
              value={closingDate}
              onChange={(e) => setClosingDate(e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create vacancy"}
        </button>
      </form>
    </PortalGuard>
  );
}
