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

  useEffect(() => {
    api
      .myApplication(params.applicationId)
      .then(setApplication)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Application not found."));
  }, [params.applicationId]);

  return (
    <div className="space-y-6">
      {error && <div className="notice border-red-200 bg-red-50 text-red-700">{error}</div>}
      {!error && !application && <DetailSkeleton />}
      {application && (
        <>
          <BackLink href="/candidate/applications" label="My applications" />
          <div className="card p-6">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
                {application.vacancy_title ?? "Vacancy"}
              </h1>
              <StatusBadge status={application.application_status} />
            </div>
            <p className="mt-2 text-sm leading-relaxed text-zinc-600">
              {STATUS_MESSAGE[application.application_status] ?? ""}
            </p>
            <p className="mt-4 text-xs text-zinc-400">
              Applied{" "}
              {new Date(application.applied_at).toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
