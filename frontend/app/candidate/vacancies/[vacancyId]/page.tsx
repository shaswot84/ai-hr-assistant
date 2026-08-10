"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { BackLink } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import type { ApplicationStatusView, Vacancy } from "@/lib/types";
import { useToast } from "@/components/toast";

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024;

function ApplySection({ vacancy }: { vacancy: Vacancy }) {
  const router = useRouter();
  const { addToast } = useToast();
  const [existing, setExisting] = useState<ApplicationStatusView | null | undefined>(undefined);
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
      addToast("Application submitted successfully.", "success");
      router.push("/candidate/applications");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to submit application.");
      setSubmitting(false);
    }
  }

  if (existing === undefined) return null;

  if (existing) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-5">
        <p className="text-sm text-emerald-900">
          You&apos;ve already applied to this role — status:{" "}
          <StatusBadge status={existing.application_status} />
        </p>
      </div>
    );
  }

  if (vacancy.status !== "OPEN") {
    return (
      <div className="card p-5">
        <p className="text-sm text-zinc-500">This vacancy is no longer accepting applications.</p>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-zinc-900">Apply</h2>
      <p className="mt-1 text-sm text-zinc-500">Upload your resume (PDF or DOCX, max 10MB).</p>
      <label className="mt-3 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-zinc-300 bg-zinc-50/50 px-4 py-8 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/40">
        <svg className="h-7 w-7 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
          />
        </svg>
        <span className="text-sm font-medium text-zinc-700">
          {file ? file.name : "Click to choose a file"}
        </span>
        <span className="text-xs text-zinc-400">Your resume is only used to screen this application.</span>
        <input type="file" accept=".pdf,.docx" onChange={handleFileChange} className="hidden" />
      </label>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      <button
        type="button"
        disabled={!file || submitting}
        onClick={handleApply}
        className="btn-primary mt-3 w-full sm:w-auto"
      >
        {submitting ? "Submitting…" : "Submit Application"}
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
    <div className="space-y-6">
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !vacancy && <DetailSkeleton />}
      {vacancy && (
        <>
          <BackLink href="/candidate" label="All vacancies" />
          <div className="card p-6">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-zinc-900">{vacancy.title}</h1>
              <StatusBadge status={vacancy.status} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-zinc-500">
              <span className="font-medium text-zinc-700">{vacancy.department_name ?? "—"}</span>
              <span className="text-zinc-300">·</span>
              <span>{vacancy.employment_type.replaceAll("_", " ")}</span>
            </div>
            {vacancy.description && (
              <p className="mt-4 max-w-3xl whitespace-pre-wrap text-sm leading-relaxed text-zinc-600">
                {vacancy.description}
              </p>
            )}
          </div>
          <ApplySection vacancy={vacancy} />
        </>
      )}
    </div>
  );
}
