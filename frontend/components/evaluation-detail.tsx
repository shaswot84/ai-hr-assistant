import type { EvaluationDetail, FeedbackSection } from "@/lib/types";
import { ScoreRing } from "./score-ring";

function Section({ title, data }: { title: string; data: FeedbackSection }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-1.5 text-xs text-muted">{data.summary || "No issues flagged."}</p>
      {data.issues.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {data.issues.map((issue, i) => (
            <li key={i} className="flex gap-1.5 text-xs">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-muted" />
              <span>{issue}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Renders the full structured AI resume evaluation: overall + job-match score
 * rings, clarity/impact/formatting feedback, missing sections, matched/missing
 * keywords, and before/after bullet rewrites. Mirrors the reference resume
 * reviewer UI.
 *
 * @param props.detail The structured evaluation detail to render.
 */
export function EvaluationDetailView({ detail }: { detail: EvaluationDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-4">
        <div className="flex items-start gap-4 rounded-lg border border-border bg-surface p-4">
          <ScoreRing score={detail.overall_score} />
          <div>
            <h3 className="text-sm font-semibold">Overall quality</h3>
            <p className="mt-1.5 text-xs text-muted">
              {detail.score_justification || "No justification provided."}
            </p>
          </div>
        </div>
        <Section title="Clarity" data={detail.clarity} />
        <Section title="Impact" data={detail.impact} />
        <Section title="Formatting" data={detail.formatting} />
      </div>

      {detail.job_match && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-start gap-4">
            <ScoreRing score={detail.job_match.match_score} />
            <div>
              <h3 className="text-sm font-semibold">Job match</h3>
              <p className="mt-1.5 text-xs text-muted">{detail.job_match.summary}</p>
            </div>
          </div>
          {(detail.job_match.matched_keywords.length > 0 ||
            detail.job_match.missing_keywords.length > 0) && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {detail.job_match.matched_keywords.length > 0 && (
                <div>
                  <p className="text-xs font-semibold">Matched</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {detail.job_match.matched_keywords.map((k, i) => (
                      <span
                        key={i}
                        className="rounded-full bg-foreground px-2.5 py-0.5 text-[11px] text-background"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {detail.job_match.missing_keywords.length > 0 && (
                <div>
                  <p className="text-xs font-semibold">Missing</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {detail.job_match.missing_keywords.map((k, i) => (
                      <span
                        key={i}
                        className="rounded-full border border-border-strong px-2.5 py-0.5 text-[11px]"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {detail.missing_sections.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-4 py-2.5">
          <span className="shrink-0 text-xs font-semibold">Missing sections</span>
          {detail.missing_sections.map((s, i) => (
            <span
              key={i}
              className="rounded-full border border-border-strong px-2.5 py-0.5 text-xs"
            >
              {s}
            </span>
          ))}
        </div>
      )}

      {detail.improved_bullets.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Bullet rewrites</h3>
          <div className="mt-2.5 grid gap-3 lg:grid-cols-2">
            {detail.improved_bullets.map((b, i) => (
              <div key={i} className="rounded-lg border border-border bg-surface p-4">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 rounded-full border border-danger/40 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-danger">
                    Before
                  </span>
                  <p className="text-xs text-muted line-through decoration-border-strong">
                    {b.original}
                  </p>
                </div>
                <div className="mt-2 flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 rounded-full border border-border-strong px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
                    After
                  </span>
                  <p className="text-xs font-medium">{b.improved}</p>
                </div>
                {b.reason && (
                  <p className="mt-2 border-t border-border pt-2 text-[11px] text-muted">
                    {b.reason}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
