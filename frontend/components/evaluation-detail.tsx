import type { Evaluation, ScoreFactor } from "@/lib/types";
import { ScoreRing } from "@/components/score-ring";

const RECOMMENDATION_STYLE: Record<string, string> = {
  "Strong Match": "bg-green-100 text-green-700",
  "Good Match": "bg-blue-100 text-blue-700",
  "Possible Match": "bg-amber-100 text-amber-700",
  "Weak Match": "bg-red-100 text-red-700",
};

function factorBarColor(score: number) {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

function ScoreFactorRow({ factor }: { factor: ScoreFactor }) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-gray-900">{factor.factor}</span>
        <span className="text-gray-500">{factor.score}/100</span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className={`h-full rounded-full ${factorBarColor(factor.score)}`}
          style={{ width: `${Math.max(0, Math.min(100, factor.score))}%` }}
        />
      </div>
      {factor.note && <p className="mt-1 text-xs text-gray-500">{factor.note}</p>}
    </div>
  );
}

/** Renders an ATS-style resume screening result for a hiring manager: does this
 * candidate match the job, why (score factors), and their pros/cons for this role. */
export function EvaluationDetail({ evaluation }: { evaluation: Evaluation }) {
  const detail = evaluation.detail;

  return (
    <div className="space-y-4">
      <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <ScoreRing score={evaluation.score} label="Match Score" />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {detail?.recommendation && (
              <span
                className={`badge ${RECOMMENDATION_STYLE[detail.recommendation] ?? "bg-gray-100 text-gray-600"}`}
              >
                {detail.recommendation}
              </span>
            )}
            {evaluation.model && <span className="text-xs text-gray-400">via {evaluation.model}</span>}
          </div>
          <p className="mt-2 text-sm text-gray-700">{evaluation.overview}</p>
        </div>
      </div>

      {detail && detail.score_factors.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Why This Score</h4>
          <div className="mt-3 space-y-3">
            {detail.score_factors.map((f) => (
              <ScoreFactorRow key={f.factor} factor={f} />
            ))}
          </div>
        </div>
      )}

      {detail && (detail.strengths.length > 0 || detail.weaknesses.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {detail.strengths.length > 0 && (
            <div className="rounded-xl border border-green-200 bg-green-50 p-4">
              <h4 className="text-sm font-semibold text-green-800">Strengths</h4>
              <ul className="mt-2 space-y-1.5">
                {detail.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-sm text-green-800">
                    <svg className="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {detail.weaknesses.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4">
              <h4 className="text-sm font-semibold text-red-800">Weaknesses</h4>
              <ul className="mt-2 space-y-1.5">
                {detail.weaknesses.map((w, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-sm text-red-800">
                    <svg className="mt-0.5 h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h4 className="text-sm font-semibold text-gray-900">Keyword Match</h4>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {detail.matched_keywords.map((kw) => (
              <span key={kw} className="badge bg-green-100 text-green-700">
                {kw}
              </span>
            ))}
            {detail.missing_keywords.map((kw) => (
              <span key={kw} className="badge bg-red-100 text-red-700 line-through">
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
