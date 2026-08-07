import type { Evaluation, FeedbackSection } from "@/lib/types";
import { ScoreRing } from "@/components/score-ring";

function Section({ title, section }: { title: string; section: FeedbackSection }) {
  if (!section.summary && section.issues.length === 0) return null;
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h4 className="text-sm font-semibold text-gray-900">{title}</h4>
      {section.summary && <p className="mt-1 text-sm text-gray-600">{section.summary}</p>}
      {section.issues.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-gray-600">
          {section.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Renders a candidate's AI resume evaluation: headline score + the full structured review. */
export function EvaluationDetail({ evaluation }: { evaluation: Evaluation }) {
  const detail = evaluation.detail;
  const headlineScore = detail?.job_match?.match_score ?? evaluation.score;

  return (
    <div className="space-y-4">
      <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <ScoreRing score={headlineScore} label={detail?.job_match ? "Job Match" : "Score"} />
        <div className="flex-1">
          <p className="text-sm text-gray-700">{evaluation.overview}</p>
          {evaluation.model && (
            <p className="mt-1 text-xs text-gray-400">Model: {evaluation.model}</p>
          )}
        </div>
      </div>

      {detail && (
        <>
          {detail.job_match && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-gray-900">Keyword Match</h4>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {detail.job_match.matched_keywords.map((kw) => (
                  <span key={kw} className="badge bg-green-100 text-green-700">
                    {kw}
                  </span>
                ))}
                {detail.job_match.missing_keywords.map((kw) => (
                  <span key={kw} className="badge bg-red-100 text-red-700 line-through">
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}

          {detail.score_justification && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-gray-900">Overall Assessment</h4>
              <p className="mt-1 text-sm text-gray-600">{detail.score_justification}</p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Section title="Clarity" section={detail.clarity} />
            <Section title="Impact" section={detail.impact} />
            <Section title="Formatting" section={detail.formatting} />
          </div>

          {detail.missing_sections.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <h4 className="text-sm font-semibold text-amber-800">Missing Sections</h4>
              <p className="mt-1 text-sm text-amber-700">{detail.missing_sections.join(", ")}</p>
            </div>
          )}

          {detail.improved_bullets.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-gray-900">Suggested Rewrites</h4>
              <div className="mt-3 space-y-3">
                {detail.improved_bullets.map((b, i) => (
                  <div key={i} className="rounded-lg bg-sky-50 p-3 text-sm">
                    <p className="text-gray-500 line-through">{b.original}</p>
                    <p className="mt-1 font-medium text-gray-900">{b.improved}</p>
                    {b.reason && <p className="mt-1 text-xs text-gray-500">{b.reason}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
