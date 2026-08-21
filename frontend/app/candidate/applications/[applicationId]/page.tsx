"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { BackLink } from "@/components/page-header";
import { StatusBadge } from "@/components/status";
import { DetailSkeleton } from "@/components/loading";
import { api, ApiError } from "@/lib/api";
import type { ApplicationStatusView } from "@/lib/types";

const STATUS_MESSAGE: Record<string, string> = {
  APPLIED: "Your application is being reviewed.",
  SHORTLISTED: "You've been shortlisted! You'll be notified about interview scheduling.",
  REJECTED: "This application was not selected to move forward.",
  WITHDRAWN: "You withdrew this application.",
};

export default function CandidateApplicationDetailPage() {
  const params = useParams<{ applicationId: string }>();
  const [application, setApplication] = useState<ApplicationStatusView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmingWithdraw, setConfirmingWithdraw] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);

  useEffect(() => {
    api
      .myApplication(params.applicationId)
      .then(setApplication)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Application not found."));
  }, [params.applicationId]);

  const handleWithdraw = async () => {
    if (!application) return;
    setWithdrawing(true);
    setError(null);
    try {
      const updated = await api.withdrawApplication(application.application_id);
      setApplication(updated);
      setConfirmingWithdraw(false);
      setSuccess("Your application has been successfully withdrawn.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to withdraw application.");
    } finally {
      setWithdrawing(false);
    }
  };

  const isWithdrawable =
    application &&
    (application.application_status === "APPLIED" ||
      application.application_status === "SHORTLISTED");

  return (
    <div className="space-y-6">
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {success && <div className="notice border-emerald-200 bg-emerald-50 text-emerald-700">{success}</div>}
      {!error && !application && <DetailSkeleton />}
      {application && (
        <>
          <BackLink href="/candidate/applications" label="My applications" />
          <div className="card p-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
                  {application.vacancy_title ?? "Vacancy"}
                </h1>
                <StatusBadge status={application.application_status} />
              </div>

              {isWithdrawable && !confirmingWithdraw && (
                <button
                  type="button"
                  onClick={() => setConfirmingWithdraw(true)}
                  className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 shadow-sm transition hover:bg-red-50 hover:border-red-300"
                >
                  Withdraw Application
                </button>
              )}
            </div>

            <p className="mt-2 text-sm leading-relaxed text-zinc-600">
              {STATUS_MESSAGE[application.application_status] ?? ""}
            </p>

            <div className="mt-4 flex flex-wrap gap-4 text-xs text-zinc-400">
              <span>
                Applied{" "}
                {new Date(application.applied_at).toLocaleDateString("en-US", {
                  month: "long",
                  day: "numeric",
                  year: "numeric",
                })}
              </span>
              {application.withdrawn_at && (
                <span>
                  · Withdrawn{" "}
                  {new Date(application.withdrawn_at).toLocaleDateString("en-US", {
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                </span>
              )}
            </div>

            {confirmingWithdraw && (
              <div className="mt-6 rounded-lg border border-red-200 bg-red-50/50 p-4">
                <h3 className="text-sm font-semibold text-red-900">
                  Withdraw this application?
                </h3>
                <p className="mt-1 text-xs text-red-700">
                  Are you sure you want to withdraw your application for{" "}
                  <span className="font-semibold">{application.vacancy_title ?? "this position"}</span>
                  ? This will remove your application from review and cannot be undone.
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleWithdraw}
                    disabled={withdrawing}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
                  >
                    {withdrawing ? "Withdrawing..." : "Yes, withdraw application"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingWithdraw(false)}
                    disabled={withdrawing}
                    className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50 disabled:opacity-50"
                  >
                    Keep application
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
