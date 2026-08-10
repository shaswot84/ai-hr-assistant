import type { Evaluation, ScoreFactor } from "@/lib/types";
import { ScoreRing } from "@/components/score-ring";

const RECOMMENDATION_STYLE: Record<string, string> = {
  "Strong Match": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Good Match": "bg-blue-50 text-blue-700 ring-blue-600/20",
  "Possible Match": "bg-amber-50 text-amber-700 ring-amber-600/20",
  "Weak Match": "bg-red-50 text-red-700 ring-red-600/20",
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
    </div>
  );
}
