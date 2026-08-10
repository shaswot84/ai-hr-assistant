"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { BackLink } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { EvaluationDetail } from "@/components/evaluation-detail";
import { DetailSkeleton } from "@/components/loading";
import { Modal } from "@/components/modal";
import { useToast } from "@/components/toast";
import { api, ApiError, downloadResume } from "@/lib/api";
import type { ApplicationDetail as ApplicationDetailType } from "@/lib/types";

function DecisionButtons({
  application,
  onChange,
}: {
  application: ApplicationDetailType;
  onChange: (a: ApplicationDetailType) => void;
}) {
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"approve" | "reject" | null>(null);

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.decide(application.application_id, action);
      onChange({ ...application, ...updated });
      addToast(
        action === "approve" ? "Application shortlisted." : "Application rejected.",
        "success"
      );
      setPendingAction(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to record decision.");
    } finally {
      setBusy(false);
    }
  }

  if (application.application_status !== "APPLIED") {
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        Already decided —
        <StatusBadge status={application.application_status} />
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => setPendingAction("approve")}
          className="btn-primary bg-emerald-600 hover:bg-emerald-700"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Shortlist
        </button>
        <button type="button" disabled={busy} onClick={() => setPendingAction("reject")} className="btn-secondary">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          Reject
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <Modal
        isOpen={pendingAction !== null}
        onClose={() => setPendingAction(null)}
        title={pendingAction === "approve" ? "Shortlist this application?" : "Reject this application?"}
        size="sm"
      >
        <p className="text-sm leading-relaxed text-zinc-600">
          {pendingAction === "approve"
            ? "The candidate will be emailed that they've been shortlisted. This decision can't be changed afterwards."
            : "The candidate will be emailed that their application wasn't selected. This decision can't be changed afterwards."}
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setPendingAction(null)}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className={
              pendingAction === "approve"
                ? "btn-primary bg-emerald-600 hover:bg-emerald-700"
                : "btn-primary bg-red-600 hover:bg-red-700"
            }
            disabled={busy}
            onClick={() => pendingAction && decide(pendingAction)}
          >
            {busy ? "Saving…" : pendingAction === "approve" ? "Shortlist" : "Reject"}
          </button>
        </div>
      </Modal>
    </div>
  );
}

function CandidateProfileCard({ application }: { application: ApplicationDetailType }) {
  const profile = application.evaluation?.detail?.candidate_profile;
  const hasProfile =
    profile && (profile.name || profile.email || profile.phone || profile.location || profile.headline);

  return (
    <div className="card p-5">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">
        Candidate Profile
      </h2>
      {hasProfile ? (
        <div className="space-y-3">
          {profile.headline && (
            <p className="text-sm font-medium text-zinc-900">{profile.headline}</p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {profile.name && (
              <div className="flex items-center gap-2 text-sm text-zinc-700">
                <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                {profile.name}
              </div>
            )}
            {profile.email && (
              <div className="flex items-center gap-2 text-sm text-zinc-700">
                <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                <span className="break-all">{profile.email}</span>
                {application.candidate_email && profile.email.toLowerCase() !== application.candidate_email.toLowerCase() && (
                  <span className="badge bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20">
                    differs from account
                  </span>
                )}
              </div>
            )}
            {profile.phone && (
              <div className="flex items-center gap-2 text-sm text-zinc-700">
                <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                </svg>
                {profile.phone}
              </div>
            )}
            {profile.location && (
              <div className="flex items-center gap-2 text-sm text-zinc-700">
                <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17.657 16.657L13.414 20.9a2 2 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {profile.location}
              </div>
            )}
          </div>
          <p className="text-xs text-zinc-400">Extracted from the resume by AI — cross-check before contacting.</p>
        </div>
      ) : (
        <p className="text-sm text-zinc-500">
          {application.evaluation
            ? "The AI screening didn't find contact details on the resume."
            : "Available once the resume screening finishes."}
        </p>
      )}
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
      await downloadResume(application.application_id, application.candidate_name ?? "resume");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !application && <DetailSkeleton />}
      {application && (
        <>
          <BackLink href="/manager/applications" label="All applications" />

          <div className="card p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-lg font-semibold text-blue-600">
                  {(application.candidate_name ?? application.candidate_email ?? "?").charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
                      {application.candidate_name ?? application.candidate_email ?? "Candidate"}
                    </h1>
                    <StatusBadge status={application.application_status} />
                  </div>
                  <p className="mt-1 text-sm text-zinc-500">
                    Applied for <span className="font-medium text-zinc-700">{application.vacancy_title ?? "this role"}</span>
                    {" · "}
                    {application.candidate_email}
                  </p>
                </div>
              </div>
              <button type="button" onClick={handleDownload} disabled={downloading} className="btn-secondary shrink-0">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
                {downloading ? "Downloading…" : "Resume"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <div className="mb-3">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  Resume Screening
                </h2>
              </div>
              {application.evaluation ? (
                <EvaluationDetail evaluation={application.evaluation} />
              ) : (
                <div className="card px-6 py-14 text-center">
                  <p className="text-sm text-zinc-500">Still screening this resume — check back shortly.</p>
                </div>
              )}
            </div>
            <div className="space-y-4">
              <div>
                <div className="mb-3">
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                    Decision
                  </h2>
                </div>
                <div className="card p-5">
                  <DecisionButtons application={application} onChange={setApplication} />
                </div>
              </div>
              <CandidateProfileCard application={application} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
