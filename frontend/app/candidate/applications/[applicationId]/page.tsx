"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PortalGuard } from "@/components/portal-guard";
import { StatusBadge } from "@/components/status";
import { EvaluationDetail } from "@/components/evaluation-detail";
import { api, ApiError } from "@/lib/api";
import type { ApplicationDetail as ApplicationDetailType } from "@/lib/types";

const STATUS_MESSAGE: Record<string, string> = {
  APPLIED: "Your application is being reviewed.",
  SHORTLISTED: "You've been shortlisted! You'll be notified about interview scheduling.",
  REJECTED: "This application was not selected to move forward.",
  WITHDRAWN: "You withdrew this application.",
};

export default function CandidateApplicationDetailPage() {
  const params = useParams<{ applicationId: string }>();
  const [application, setApplication] = useState<ApplicationDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .myApplication(params.applicationId)
      .then(setApplication)
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Application not found."));
  }, [params.applicationId]);

  return (
    <PortalGuard allowedRoles={["CANDIDATE"]}>
      <div className="animate-fade-in space-y-6">
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!error && !application && <p className="text-sm text-gray-500">Loading…</p>}
        {application && (
          <>
            <div className="card p-6">
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-gray-900">{application.vacancy_title ?? "Vacancy"}</h1>
                <StatusBadge status={application.application_status} />
              </div>
              <p className="mt-1 text-sm text-gray-500">
                {STATUS_MESSAGE[application.application_status] ?? ""}
              </p>
            </div>

            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-500">
                AI Resume Review
              </h2>
              {application.evaluation ? (
                <EvaluationDetail evaluation={application.evaluation} />
              ) : (
                <div className="card p-8 text-center">
                  <p className="text-sm text-gray-500">Your resume is still being evaluated — check back shortly.</p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </PortalGuard>
  );
}
