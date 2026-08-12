"use client";

import { useState } from "react";
import type { Application, Evaluation, KeyFactor, Requirement, WorkExperienceEntry } from "@/lib/types";
import { DOES_NOT_MEET_REQUIREMENTS } from "@/lib/types";
import { api, ApiError } from "@/lib/api";

const RECOMMENDATION_STYLE: Record<string, string> = {
  "Strong Match": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Good Match": "bg-blue-50 text-blue-700 ring-blue-600/20",
  "Possible Match": "bg-amber-50 text-amber-700 ring-amber-600/20",
  "Weak Match": "bg-red-50 text-red-700 ring-red-600/20",
  [DOES_NOT_MEET_REQUIREMENTS]: "bg-red-100 text-red-800 ring-red-600/30",
};

function KeyFactorRow({ factor }: { factor: KeyFactor }) {
  return (
    <div>
      <p className="text-sm font-medium text-zinc-900">{factor.factor}</p>
      {factor.note && <p className="mt-1 text-xs leading-relaxed text-zinc-500">{factor.note}</p>}
    </div>
  );
}

function RequirementRow({ requirement }: { requirement: Requirement }) {
  return (
    <div className="flex items-start gap-2.5">
      {requirement.met ? (
        <svg className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="mt-0.5 h-4 w-4 shrink-0 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
        </svg>
      )}
      <div className="min-w-0">
        <p className={`text-sm font-medium ${requirement.met ? "text-zinc-900" : "text-red-900"}`}>
          {requirement.requirement}
        </p>
        {requirement.evidence && (
          <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">{requirement.evidence}</p>
        )}
      </div>
    </div>
  );
}

/** The hard-requirements gate — shown first and unmissable, since a candidate who fails
 * a stated must-have shouldn't be judged by the same fuzzy label as a soft-fit mismatch. */
function RequirementsGate({
  requirements,
  requirementsMet,
}: {
  requirements: Requirement[];
  requirementsMet: boolean;
}) {
  if (requirements.length === 0) return null;

  return (
    <div
      className={`card border p-5 ${
        requirementsMet ? "border-emerald-200/70 bg-emerald-50/40" : "border-red-300 bg-red-50/60"
      }`}
    >
      <div className="flex items-center gap-2">
        {requirementsMet ? (
          <span className="badge bg-emerald-100 text-emerald-800 ring-1 ring-inset ring-emerald-600/30">
            Meets all stated requirements
          </span>
        ) : (
          <span className="badge bg-red-100 text-red-800 ring-1 ring-inset ring-red-600/30">
            {DOES_NOT_MEET_REQUIREMENTS}
          </span>
        )}
        <span className="text-xs text-zinc-500">
          {requirements.filter((r) => r.met).length} of {requirements.length} must-haves met
        </span>
      </div>
      <div className="mt-4 space-y-3">
        {requirements.map((r, i) => (
          <RequirementRow key={i} requirement={r} />
        ))}
      </div>
    </div>
  );
}

function formatDateRange(entry: WorkExperienceEntry) {
  // Only trust the raw date string if it parsed to a real year — a garbled
  // extraction (no recognizable year) shows as "?" instead of the raw
  // text, matching what the years-of-experience total already excludes it from.
  const start = entry.start_year !== null ? entry.start_date || "?" : "?";
  const end = entry.is_current ? "Present" : entry.end_year !== null ? entry.end_date || "?" : "?";
  return `${start} – ${end}`;
}

/** Structured facts pulled from the resume (work history, education, skills) — the
 * verified basis behind the AI's assessment, so a manager can sanity-check it directly.
 * Rendered in the page's sidebar (below the candidate profile), not inline here. */
export function ExperienceEducationCard({
  structured,
}: {
  structured: NonNullable<Evaluation["detail"]>["structured_resume"];
}) {
  if (!structured) return null;
  const hasContent =
    structured.work_experience.length > 0 || structured.education.length > 0 || structured.skills.length > 0;
  if (!hasContent) return null;

  return (
    <div className="card p-5">
      <div className="space-y-0.5">
        <h4 className="text-sm font-semibold text-zinc-900">Experience &amp; Education</h4>
        {structured.total_years_experience > 0 && (
          <p className="text-xs text-zinc-500">
            <span className="font-semibold tabular-nums text-zinc-700">
              {structured.total_years_experience}
            </span>{" "}
            years total — computed from resume dates
          </p>
        )}
      </div>

      {structured.work_experience.length > 0 && (
        <ul className="mt-4 space-y-3 border-l border-zinc-200 pl-4">
          {structured.work_experience.map((entry, i) => (
            <li key={i} className="relative">
              <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-zinc-300" />
              <p className="text-sm font-medium text-zinc-900">
                {entry.title || "Unknown title"}
                {entry.company && <span className="font-normal text-zinc-500"> · {entry.company}</span>}
              </p>
              <p className="text-xs text-zinc-400">{formatDateRange(entry)}</p>
            </li>
          ))}
        </ul>
      )}

      {structured.education.length > 0 && (
        <div className="mt-4 space-y-1.5 border-t border-zinc-100 pt-4">
          {structured.education.map((entry, i) => (
            <p key={i} className="text-sm text-zinc-700">
              {entry.degree || "Degree"}
              {entry.institution && <span className="text-zinc-500">, {entry.institution}</span>}
              {entry.graduation_year && <span className="text-zinc-400"> ({entry.graduation_year})</span>}
            </p>
          ))}
        </div>
      )}

      {structured.skills.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5 border-t border-zinc-100 pt-4">
          {structured.skills.map((skill) => (
            <span key={skill} className="badge bg-zinc-100 text-zinc-600 ring-1 ring-inset ring-zinc-500/20">
              {skill}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Shown when the screening couldn't run at all (e.g. no AI provider configured) —
 * a clear error instead of a fabricated result, with a one-click retry. */
function FailedEvaluation({
  evaluation,
  applicationId,
  onRetried,
}: {
  evaluation: Evaluation;
  applicationId: string;
  onRetried: (application: Application) => void;
}) {
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justRetried, setJustRetried] = useState(false);

  async function retry() {
    setRetrying(true);
    setError(null);
    try {
      const updated = await api.reEvaluate(applicationId);
      onRetried(updated);
      setJustRetried(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to start re-screening.");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="card border border-red-300 bg-red-50/60 p-5">
      <div className="flex items-start gap-3">
        <svg className="mt-0.5 h-5 w-5 shrink-0 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-red-800">AI screening couldn&apos;t run</p>
          <p className="mt-1 text-sm leading-relaxed text-red-700">{evaluation.overview}</p>
          {justRetried && !error && (
            <p className="mt-2 text-sm text-emerald-700">
              Re-screening started — check back shortly for the result.
            </p>
          )}
          {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
          <button
            type="button"
            disabled={retrying}
            onClick={retry}
            className="btn-secondary mt-3 border-red-300 text-red-700 hover:bg-red-100"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            {retrying ? "Re-screening…" : "Re-run Screening"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Renders an ATS-style resume screening result for a hiring manager: does this
 * candidate match the job, why (key factors), and their pros/cons for this role. */
export function EvaluationDetail({
  evaluation,
  applicationId,
  onRetried,
}: {
  evaluation: Evaluation;
  applicationId: string;
  onRetried: (application: Application) => void;
}) {
  const detail = evaluation.detail;

  if (evaluation.failed) {
    return <FailedEvaluation evaluation={evaluation} applicationId={applicationId} onRetried={onRetried} />;
  }

  return (
    <div className="space-y-4">
      {detail && <RequirementsGate requirements={detail.requirements} requirementsMet={detail.requirements_met} />}

      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          {/* Skip repeating the badge here when it's DOES_NOT_MEET_REQUIREMENTS —
              the requirements gate above already leads with that exact label. */}
          {detail?.recommendation && detail.recommendation !== DOES_NOT_MEET_REQUIREMENTS && (
            <span
              className={`badge ring-1 ring-inset ${RECOMMENDATION_STYLE[detail.recommendation] ?? "bg-zinc-100 text-zinc-600 ring-zinc-500/20"}`}
            >
              {detail.recommendation}
            </span>
          )}
          {evaluation.model && (
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-500">
              {evaluation.model}
            </span>
          )}
        </div>
        <p className="mt-2 text-sm leading-relaxed text-zinc-600">{evaluation.overview}</p>
      </div>

      {detail && detail.key_factors.length > 0 && (
        <div className="card p-5">
          <h4 className="text-sm font-semibold text-zinc-900">Key Factors</h4>
          <div className="mt-4 space-y-4">
            {detail.key_factors.map((f) => (
              <KeyFactorRow key={f.factor} factor={f} />
            ))}
          </div>
        </div>
      )}

      {detail && (detail.strengths.length > 0 || detail.weaknesses.length > 0) && (
        <div className="grid gap-4 sm:grid-cols-2">
          {detail.strengths.length > 0 && (
            <div className="rounded-lg border border-emerald-200/70 bg-emerald-50/60 p-4">
              <h4 className="text-[13px] font-semibold text-emerald-800">Strengths</h4>
              <ul className="mt-2.5 space-y-1.5">
                {detail.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-[13px] leading-relaxed text-emerald-900">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {detail.weaknesses.length > 0 && (
            <div className="rounded-lg border border-red-200/70 bg-red-50/60 p-4">
              <h4 className="text-[13px] font-semibold text-red-800">Weaknesses</h4>
              <ul className="mt-2.5 space-y-1.5">
                {detail.weaknesses.map((w, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-[13px] leading-relaxed text-red-900">
                    <svg className="mt-0.5 h-4 w-4 shrink-0 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {detail && (detail.matched_keywords.length > 0 || detail.missing_keywords.length > 0) && (
        <div className="card p-5">
          <h4 className="text-sm font-semibold text-zinc-900">Keyword Match</h4>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {detail.matched_keywords.map((kw) => (
              <span key={kw} className="badge bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                {kw}
              </span>
            ))}
            {detail.missing_keywords.map((kw) => (
              <span key={kw} className="badge bg-red-50 text-red-700 line-through ring-1 ring-inset ring-red-600/20">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
