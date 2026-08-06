import type { Evaluation, FeedbackSection } from "@/lib/types";
import { ScoreRing } from "@/components/score-ring";

function Section({ title, section }: { title: string; section: FeedbackSection }) {
  if (!section.summary && section.issues.length === 0) return null;
  return (
    <div className="rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium">{title}</h4>
      {section.summary && <p className="mt-1 text-sm text-muted">{section.summary}</p>}
      {section.issues.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-muted">
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface p-4">
        <ScoreRing
          score={detail?.job_match?.match_score ?? evaluation.score}
          label={detail?.job_match ? "Job match" : "Score"}
        />
        <p className="flex-1 text-sm text-muted">{evaluation.overview}</p>
      </div>

      {detail && (
        <>
          {detail.job_match && (
            <div className="rounded-lg border border-border p-4">
              <h4 className="text-sm font-medium">Keyword match</h4>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {detail.job_match.matched_keywords.map((kw) => (
                  <span
                    key={kw}
                    className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"
                  >
                    {kw}
                  </span>
                ))}
                {detail.job_match.missing_keywords.map((kw) => (
                  <span
                    key={kw}
                    className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-700 line-through"
                  >
                    {kw}
                  </span>
                ))}
              </div>
            </div>
          )}

          {detail.score_justification && (
            <div className="rounded-lg border border-border p-4">
              <h4 className="text-sm font-medium">Overall assessment</h4>
              <p className="mt-1 text-sm text-muted">{detail.score_justification}</p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Section title="Clarity" section={detail.clarity} />
            <Section title="Impact" section={detail.impact} />
            <Section title="Formatting" section={detail.formatting} />
          </div>

          {detail.missing_sections.length > 0 && (
            <div className="rounded-lg border border-border p-4">
              <h4 className="text-sm font-medium">Missing sections</h4>
              <p className="mt-1 text-sm text-muted">{detail.missing_sections.join(", ")}</p>
            </div>
          )}

          {detail.improved_bullets.length > 0 && (
            <div className="rounded-lg border border-border p-4">
              <h4 className="text-sm font-medium">Suggested rewrites</h4>
              <div className="mt-2 space-y-3">
                {detail.improved_bullets.map((b, i) => (
                  <div key={i} className="text-sm">
                    <p className="text-muted line-through">{b.original}</p>
                    <p className="mt-0.5">{b.improved}</p>
                    {b.reason && <p className="mt-0.5 text-xs text-muted">{b.reason}</p>}
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
