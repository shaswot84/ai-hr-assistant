"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { EvaluationDetail } from "@/components/evaluation-detail";
import { api, ApiError, downloadResume } from "@/lib/api";
import type { ApplicationDetail as ApplicationDetailType } from "@/lib/types";

function DecisionButtons({
  application,
  onChange,
}: {
  application: ApplicationDetailType;
  onChange: (a: ApplicationDetailType) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.decide(application.application_id, action);
      onChange({ ...application, ...updated });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to record decision.");
    } finally {
      setBusy(false);
    }
  }

  if (application.application_status !== "APPLIED") {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500">
        Already decided —
        <StatusBadge status={application.application_status} />
      </div>
    );
  }

  return (
    <div>
      <div className="flex gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => decide("approve")}
          className="btn-primary bg-green-600 hover:bg-green-700"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Shortlist
        </button>
        <button type="button" disabled={busy} onClick={() => decide("reject")} className="btn-secondary">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          Reject
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

export default function ManagerApplicationDetailPage() {
  const params = useParams<{ applicationId: string }>();
  const [application, setApplication] = useState<ApplicationDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    api
      .applicationDetail(params.applicationId)
      .then(setApplication)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Application not found."));
  }, [params.applicationId]);

  async function handleDownload() {
    if (!application) return;
    setDownloading(true);
    try {
      await downloadResume(
        application.application_id,
        `${application.candidate_name ?? "resume"}.pdf`
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <PortalGuard allowedRoles={["HR_ADMIN"]}>
      <div className="animate-fade-in space-y-6">
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!error && !application && <p className="text-sm text-gray-500">Loading…</p>}
        {application && (
          <>
            <div className="card flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-lg font-bold text-blue-600">
                  {(application.candidate_name ?? application.candidate_email ?? "?").charAt(0).toUpperCase()}
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h1 className="text-xl font-bold text-gray-900">
                      {application.candidate_name ?? application.candidate_email ?? "Candidate"}
                    </h1>
                    <StatusBadge status={application.application_status} />
                  </div>
                  <p className="mt-1 text-sm text-gray-500">
                    Applied for {application.vacancy_title ?? "this role"} · {application.candidate_email}
                  </p>
                </div>
              </div>
              <button type="button" onClick={handleDownload} disabled={downloading} className="btn-secondary">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
                {downloading ? "Downloading…" : "Resume"}
              </button>
            </div>

            <div className="card p-6">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-500">
                Decision
              </h2>
              <DecisionButtons application={application} onChange={setApplication} />
            </div>

            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-500">
                AI Resume Review
              </h2>
              {application.evaluation ? (
                <EvaluationDetail evaluation={application.evaluation} />
              ) : (
                <div className="card p-8 text-center">
                  <p className="text-sm text-gray-500">Still evaluating this resume — check back shortly.</p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </PortalGuard>
  );
}
