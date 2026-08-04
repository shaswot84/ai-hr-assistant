"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge, formatDate } from "@/components/status";
import { api } from "@/lib/api";
import type { Vacancy } from "@/lib/types";

const ACCEPTED_EXT = [".pdf", ".docx"];

function isAcceptedFile(file: File): boolean {
  return ACCEPTED_EXT.some((ext) => file.name.toLowerCase().endsWith(ext));
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function CandidateVacancyDetailPage({
  params,
}: {
  params: Promise<{ vacancyId: string }>;
}) {
  const [vacancyId, setVacancyId] = useState<string | null>(null);
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    params.then(({ vacancyId }) => setVacancyId(vacancyId));
  }, [params]);

  useEffect(() => {
    if (!vacancyId) return;
    api
      .getVacancy(vacancyId)
      .then(setVacancy)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load vacancy"));
  }, [vacancyId]);

  async function apply() {
    if (!file || !vacancyId) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const app = await api.apply(vacancyId, file);
      setResult(`Application submitted (${app.application_status}).`);
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="animate-fade-in mx-auto max-w-2xl">
        <Link href="/candidate" className="text-xs text-muted transition-colors hover:text-foreground">
          ← Back to vacancies
        </Link>

        {error && !vacancy && <p className="mt-6 text-sm text-danger">{error}</p>}

        {!vacancy && !error && <p className="mt-6 text-sm text-muted">Loading…</p>}

        {vacancy && (
          <>
            <div className="mt-4 flex items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold tracking-tight">{vacancy.title}</h1>
                <p className="mt-1 text-sm text-muted">
                  {vacancy.department_name ?? "—"} · {vacancy.employment_type.replace("_", " ")}
                </p>
              </div>
              <StatusBadge status={vacancy.status} />
            </div>

            <p className="mt-4 text-sm text-muted">Closes {formatDate(vacancy.closing_date)}</p>

            {vacancy.description && (
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed">{vacancy.description}</p>
            )}

            {vacancy.status !== "OPEN" ? (
              <p className="mt-8 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted">
                This vacancy is not open for applications.
              </p>
            ) : (
              <div className="mt-8 rounded-xl border border-border bg-surface p-5">
                <h2 className="text-sm font-semibold">Apply with your resume</h2>
                <label className="mt-4 block cursor-pointer rounded-xl border border-dashed border-border-strong px-4 py-6 text-center text-sm text-muted transition-colors hover:bg-surface-hover">
                  {file ? (
                    <>
                      <span className="font-medium text-foreground">{file.name}</span>
                      <span className="ml-2">({formatBytes(file.size)})</span>
                    </>
                  ) : (
                    "Choose a resume (PDF or DOCX, up to 10MB)"
                  )}
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    className="hidden"
                    onChange={(e) => {
                      const selected = e.target.files?.[0];
                      if (selected && !isAcceptedFile(selected)) {
                        setError("Please upload a .pdf or .docx file.");
                        setFile(null);
                      } else {
                        setError(null);
                        setFile(selected ?? null);
                      }
                      e.target.value = "";
                    }}
                  />
                </label>

                {error && <p className="mt-3 text-sm text-danger">{error}</p>}
                {result && <p className="mt-3 text-sm text-foreground">{result}</p>}

                <button
                  type="button"
                  onClick={apply}
                  disabled={!file || submitting}
                  className="mt-4 w-full rounded-full bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {submitting ? "Submitting…" : "Submit application"}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </PortalGuard>
  );
}