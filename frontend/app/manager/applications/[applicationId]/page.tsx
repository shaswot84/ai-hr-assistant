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
      <p className="text-sm text-muted">
        This application has already been decided (<StatusBadge status={application.application_status} />
        ).
      </p>
    );
  }

  return (
    <div>
      <div className="flex gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => decide("approve")}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Shortlist
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => decide("reject")}
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium transition-colors hover:bg-surface-hover disabled:opacity-50"
        >
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
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!error && !application && <p className="text-sm text-muted">Loading…</p>}
      {application && (
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-semibold">
                  {application.candidate_name ?? application.candidate_email ?? "Candidate"}
                </h1>
                <StatusBadge status={application.application_status} />
              </div>
              <p className="mt-1 text-sm text-muted">
                Applied for {application.vacancy_title ?? "this role"} ·{" "}
                {application.candidate_email}
              </p>
            </div>
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              {downloading ? "Downloading…" : "Download resume"}
            </button>
          </div>

          <div className="rounded-xl border border-border bg-surface p-5">
            <h2 className="mb-3 text-sm font-medium">Decision</h2>
            <DecisionButtons application={application} onChange={setApplication} />
          </div>

          <div>
            <h2 className="mb-2 text-sm font-medium">AI resume review</h2>
            {application.evaluation ? (
              <EvaluationDetail evaluation={application.evaluation} />
            ) : (
              <p className="text-sm text-muted">Still evaluating this resume — check back shortly.</p>
            )}
          </div>
        </div>
      )}
    </PortalGuard>
  );
}
