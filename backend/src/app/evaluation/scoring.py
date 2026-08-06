from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

PROMPT_VERSION = "recruitment-score-v2"

#: Default system prompt instructing the model how to behave. Managers can
#: override this at runtime through the Settings page; that override is stored
#: in the ``app_setting`` table and passed in via ``score_resume``.
DEFAULT_SYSTEM_PROMPT = (
    "You are a senior technical recruiter for a startup. You review how well a "
    "candidate's resume matches a specific job posting with a critical, honest "
    "eye. Be grounded only in the resume text provided — never invent experience "
    "the candidate does not have. Respond with ONLY a single valid JSON object "
    "matching the schema in the user message. No markdown fences, no commentary."
)

USER_PROMPT = """Review the following resume for fit against a target job.

TARGET JOB:
Title: {job_title}
Description:
{job_description}

RESUME TEXT (raw-extracted, may have imperfect spacing/line breaks — look past formatting artifacts to the content):
{resume_text}

Return a single JSON object with exactly this shape:
{{
  "overallScore": number,               // 0-100 overall resume quality
  "scoreJustification": string,         // 2-4 sentences explaining the overall score
  "clarity": {{
    "summary": string,
    "issues": string[]
  }},
  "impact": {{
    "summary": string,
    "issues": string[]
  }},
  "formatting": {{
    "summary": string,
    "issues": string[]
  }},
  "missingSections": string[],          // e.g. ["Education", "Contact Info"], empty if none
  "improvedBullets": [                  // at least 3, each "original" copied verbatim from the resume
    {{"original": string, "improved": string, "reason": string}}
  ],
  "jobMatch": {{
    "matchScore": number,               // 0-100, how well the resume matches the target job
    "summary": string,
    "matchedKeywords": string[],        // job requirements evidenced in the resume
    "missingKeywords": string[]         // important job requirements absent from the resume
  }}
}}
Rules:
- score/clarity/impact/formatting/jobMatch must be JSON objects or numbers as shown; arrays even when empty.
- "improvedBullets" MUST contain at least 3 entries, each "original" copied verbatim from the resume text above.
- Do not fabricate metrics that contradict the resume; where a number is unknown, phrase the improvement around scope, ownership, or outcome.
- Ground everything in the resume text. Output raw JSON only."""


@dataclass
class ScoreResult:
    """Structured outcome of a resume-vs-job evaluation.

    ``score``/``overview`` are the compact columns; the full verbose review is
    kept in ``raw_payload`` for the richer manager-facing evaluation UI.
    """

    score: int
    overview: str
    raw_payload: dict[str, Any]
    model: str
    prompt_version: str


def _clamp_score(value: Any) -> int:
    """Coerce and clamp a raw score into the valid 0-100 integer range (0 on failure)."""
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return 0


def _str(value: Any, fallback: str = "") -> str:
    """Return `value` if it is a string, otherwise the given fallback."""
    return value if isinstance(value, str) else fallback


def _str_list(value: Any) -> list[str]:
    """Return the list of strings contained in `value` (empty list for non-list inputs)."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _section(value: Any) -> dict[str, Any]:
    """Normalize a clarity/impact/formatting section into {summary, issues}."""
    s = value if isinstance(value, dict) else {}
    issues = s.get("issues")
    return {
        "summary": _str(s.get("summary")),
        "issues": _str_list(issues),
    }


def _bullets(value: Any) -> list[dict[str, str]]:
    """Normalize the improvedBullets list into [{original, improved, reason}]."""
    result: list[dict[str, str]] = []
    if not isinstance(value, list):
        return result
    for b in value:
        if not isinstance(b, dict):
            continue
        original = _str(b.get("original"))
        improved = _str(b.get("improved"))
        if original and improved:
            result.append(
                {
                    "original": original,
                    "improved": improved,
                    "reason": _str(b.get("reason")),
                }
            )
    return result


def _normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw model payload into a well-typed, defensively-parsed review object.

    Missing/odd-shaped fields fall back to empty/safe defaults so the UI never
    breaks on a partially malformed model response.
    """
    job_match_raw = data.get("jobMatch")
    job_match: dict[str, Any] | None = None
    if isinstance(job_match_raw, dict):
        job_match = {
            "matchScore": _clamp_score(job_match_raw.get("matchScore")),
            "summary": _str(job_match_raw.get("summary")),
            "matchedKeywords": _str_list(job_match_raw.get("matchedKeywords")),
            "missingKeywords": _str_list(job_match_raw.get("missingKeywords")),
        }

    overall = _clamp_score(data.get("overallScore"))
    justification = _str(data.get("scoreJustification"), "No justification provided.")

    return {
        "overallScore": overall,
        "scoreJustification": justification,
        "clarity": _section(data.get("clarity")),
        "impact": _section(data.get("impact")),
        "formatting": _section(data.get("formatting")),
        "missingSections": _str_list(data.get("missingSections")),
        "improvedBullets": _bullets(data.get("improvedBullets")),
        "jobMatch": job_match,
    }


async def score_resume(
    *,
    resume_text: str,
    job_title: str,
    job_description: str,
    system_prompt: str | None = None,
) -> ScoreResult:
    """Score a resume against a job using the Ollama hosted API.

    ``system_prompt`` lets a manager override the model instructions (stored in
    settings); when None, the default constant is used. If the API key is
    missing (local dev without secrets), falls back to a deterministic
    keyword-match scorer so the pipeline stays demoable.
    """
    provider = OllamaChatProvider()
    if provider.is_configured():
        return await _score_with_llm(
            provider, resume_text, job_title, job_description, system_prompt
        )
    return _score_deterministic(resume_text, job_title, job_description)


async def _score_with_llm(
    provider: OllamaChatProvider,
    resume_text: str,
    job_title: str,
    job_description: str,
    system_prompt: str | None,
) -> ScoreResult:
    """Score the resume via the Ollama chat provider, falling back to the deterministic scorer."""
    user_prompt = USER_PROMPT.format(
        job_title=job_title,
        job_description=job_description or "Not provided.",
        resume_text=resume_text[:12000],
    )
    try:
        data = await provider.complete_json(
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except ChatProviderError:
        # graceful degradation per error-handling principles: fall back, never crash
        return _score_deterministic(resume_text, job_title, job_description)

    review = _normalize_review(data)
    return ScoreResult(
        score=_score_primary(review),
        overview=_overview_primary(review),
        raw_payload=review,
        model=provider._model,
        prompt_version=PROMPT_VERSION,
    )


def _score_primary(review: dict[str, Any]) -> int:
    """Pick the headline score: the job-match score when present, else overall quality."""
    job_match = review.get("jobMatch")
    return _clamp_score(job_match.get("matchScore")) if job_match else review.get("overallScore", 0)


def _overview_primary(review: dict[str, Any]) -> str:
    """Pick the headline overview: the job-match summary when present, else the quality justification."""
    job_match = review.get("jobMatch")
    if job_match and _str(job_match.get("summary")):
        return _str(job_match.get("summary"))
    return _str(review.get("scoreJustification"), "No overview provided.")


def _score_deterministic(
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    """Zero-dependency fallback: term-overlap matching when no Ollama key is set.

    Tokenizes the job description into keywords, counts how many appear in the
    resume, and produces a heuristic score + a structured review. Explicitly a
    fallback — the real scoring is the LLM path.
    """
    resume_lower = resume_text.lower()
    job_lower = job_description.lower() if job_description else job_title.lower()

    keywords = _extract_keywords(job_lower)
    if not keywords:
        review = {
            "overallScore": 50,
            "scoreJustification": (
                "No job description was provided, so the score is a neutral estimate. "
                "Add a job description for a meaningful AI evaluation. "
                "Separate clarity/impact/formatting reviews are unavailable in fallback mode."
            ),
            "clarity": {"summary": "", "issues": []},
            "impact": {"summary": "", "issues": []},
            "formatting": {"summary": "", "issues": []},
            "missingSections": [],
            "improvedBullets": [],
            "jobMatch": {
                "matchScore": 50,
                "summary": "No job description was provided, so the match score is neutral.",
                "matchedKeywords": [],
                "missingKeywords": [],
            },
        }
        return ScoreResult(
            score=50,
            overview=_str(review.get("jobMatch", {}).get("summary")),
            raw_payload=review,
            model="deterministic-fallback",
            prompt_version=PROMPT_VERSION,
        )

    matched = [kw for kw in keywords if kw in resume_lower]
    missing = [kw for kw in keywords if kw not in resume_lower]
    score = round(100 * len(matched) / len(keywords))

    if score >= 70:
        match_summary = (
            f"Strong match: {len(matched)} of {len(keywords)} key requirements are evidenced in the resume."
        )
    elif score >= 40:
        match_summary = (
            f"Partial match: {len(matched)} of {len(keywords)} key requirements were found, "
            "but important gaps remain."
        )
    else:
        match_summary = (
            f"Weak match: only {len(matched)} of {len(keywords)} key requirements were found. "
            "Significant gaps exist."
        )

    review = {
        "overallScore": score,
        "scoreJustification": (
            f"The resume shares {len(matched)} of {len(keywords)} key requirements with the job. "
            "This is a keyword-based fallback, not a full LLM review."
        ),
        "clarity": {"summary": "", "issues": []},
        "impact": {"summary": "", "issues": []},
        "formatting": {"summary": "", "issues": []},
        "missingSections": [],
        "improvedBullets": [],
        "jobMatch": {
            "matchScore": score,
            "summary": match_summary,
            "matchedKeywords": matched,
            "missingKeywords": missing,
        },
    }

    return ScoreResult(
        score=score,
        overview=match_summary,
        raw_payload=review,
        model="deterministic-fallback",
        prompt_version=PROMPT_VERSION,
    )


def _extract_keywords(job_lower: str, limit: int = 25) -> list[str]:
    """Pull meaningful keywords (>= 4 chars, alphabetic) from the job text."""
    words = set()
    for token in re.split(r"[^a-z0-9+#.]+", job_lower):
        token = token.strip().lower()
        if len(token) >= 4 and not token.isdigit():
            words.add(token)
    ordered = sorted(words)
    return ordered[:limit]
