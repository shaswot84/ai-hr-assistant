"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { api, ApiError } from "@/lib/api";
import type { Application, Vacancy } from "@/lib/types";

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024;

function ApplySection({ vacancy }: { vacancy: Vacancy }) {
  const router = useRouter();
  const [existing, setExisting] = useState<Application | null | undefined>(undefined);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .myApplications()
      .then((apps) => setExisting(apps.find((a) => a.vacancy_id === vacancy.vacancy_id) ?? null))
      .catch(() => setExisting(null));
  }, [vacancy.vacancy_id]);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null);
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setFile(null);
      return;
    }
    const lower = f.name.toLowerCase();
    if (!ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      setError("Only PDF or DOCX resumes are accepted.");
      setFile(null);
      return;
    }
    if (f.size > MAX_BYTES) {
      setError("Resume too large. Max size is 10MB.");
      setFile(null);
      return;
    }
    setFile(f);
  }

  async function handleApply() {
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.apply(vacancy.vacancy_id, file);
      router.push("/candidate/applications");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to submit application.");
      setSubmitting(false);
    }
  }

  if (existing === undefined) return null;

  if (existing) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5">
        <p className="text-sm">
          You&apos;ve already applied to this role —{" "}
          <span className="font-medium">status: </span>
          <StatusBadge status={existing.application_status} />
        </p>
      </div>
    );
  }

  if (vacancy.status !== "OPEN") {
    return (
      <div className="rounded-xl border border-border bg-surface p-5">
        <p className="text-sm text-muted">This vacancy is no longer accepting applications.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <h2 className="text-sm font-medium">Apply</h2>
      <p className="mt-1 text-sm text-muted">Upload your resume (PDF or DOCX, max 10MB).</p>
      <input
        type="file"
        accept=".pdf,.docx"
        onChange={handleFileChange}
        className="mt-3 block w-full text-sm file:mr-3 file:rounded-lg file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-sm file:font-medium"
      />
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <button
        type="button"
        disabled={!file || submitting}
        onClick={handleApply}
        className="mt-3 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit application"}
      </button>
    </div>
  );
}

export default function VacancyDetailPage() {
  const params = useParams<{ vacancyId: string }>();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getVacancy(params.vacancyId)
      .then(setVacancy)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Vacancy not found."));
  }, [params.vacancyId]);

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!error && !vacancy && <p className="text-sm text-muted">Loading…</p>}
      {vacancy && (
        <div className="space-y-6">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold">{vacancy.title}</h1>
              <StatusBadge status={vacancy.status} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {vacancy.department_name ?? "—"} · {vacancy.employment_type.replaceAll("_", " ")}
            </p>
          </div>
          {vacancy.description && (
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{vacancy.description}</p>
          )}
          <ApplySection vacancy={vacancy} />
        </div>
      )}
    </PortalGuard>
  );
}
