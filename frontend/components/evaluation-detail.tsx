import type { Evaluation, Requirement, ScoreFactor, WorkExperienceEntry } from "@/lib/types";
import { DOES_NOT_MEET_REQUIREMENTS } from "@/lib/types";
import { ScoreRing } from "@/components/score-ring";

const RECOMMENDATION_STYLE: Record<string, string> = {
  "Strong Match": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Good Match": "bg-blue-50 text-blue-700 ring-blue-600/20",
  "Possible Match": "bg-amber-50 text-amber-700 ring-amber-600/20",
  "Weak Match": "bg-red-50 text-red-700 ring-red-600/20",
  [DOES_NOT_MEET_REQUIREMENTS]: "bg-red-100 text-red-800 ring-red-600/30",
};

function factorBarColor(score: number) {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

function ScoreFactorRow({ factor }: { factor: ScoreFactor }) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-zinc-900">{factor.factor}</span>
        <span className="tabular-nums text-zinc-500">{factor.score}/100</span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${factorBarColor(factor.score)}`}
          style={{ width: `${Math.max(0, Math.min(100, factor.score))}%` }}
        />
      </div>
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
 * a stated must-have shouldn't be judged by the same fuzzy score as a soft-fit mismatch. */
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
 * verified basis behind the AI's score, so a manager can sanity-check it directly. */
function ExperienceEducationCard({
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
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-zinc-900">Experience &amp; Education</h4>
        {structured.total_years_experience > 0 && (
          <span className="text-xs text-zinc-500">
            <span className="font-semibold tabular-nums text-zinc-700">
              {structured.total_years_experience}
            </span>{" "}
            years total — computed from resume dates
          </span>
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

/** Renders an ATS-style resume screening result for a hiring manager: does this
 * candidate match the job, why (score factors), and their pros/cons for this role. */
export function EvaluationDetail({ evaluation }: { evaluation: Evaluation }) {
  const detail = evaluation.detail;

  return (
    <div className="space-y-4">
      {detail && <RequirementsGate requirements={detail.requirements} requirementsMet={detail.requirements_met} />}

      <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <ScoreRing score={evaluation.score} label="Match Score" />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {detail?.recommendation && (
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
      </div>

      {detail && detail.score_factors.length > 0 && (
        <div className="card p-5">
          <h4 className="text-sm font-semibold text-zinc-900">Why This Score</h4>
          <div className="mt-4 space-y-4">
            {detail.score_factors.map((f) => (
              <ScoreFactorRow key={f.factor} factor={f} />
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

      {detail && <ExperienceEducationCard structured={detail.structured_resume} />}
    </div>
  );
}
