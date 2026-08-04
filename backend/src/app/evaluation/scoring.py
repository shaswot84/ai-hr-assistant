from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

PROMPT_VERSION = "recruitment-score-v1"

SYSTEM_PROMPT = (
    "You are a senior technical recruiter for a startup. You evaluate how well a "
    "candidate's resume matches a specific job posting. Be honest and grounded only "
    "in the resume text provided — never invent experience the candidate does not "
    "have. Respond with ONLY a single valid JSON object matching the schema in the "
    "user message. No markdown fences, no commentary."
)

USER_PROMPT = """Evaluate the fit of this resume for the target job.

TARGET JOB:
Title: {job_title}
Description:
{job_description}

RESUME TEXT (raw-extracted, spacing may be imperfect):
{resume_text}

Return a single JSON object with exactly this shape:
{{
  "score": number,            // 0-100, how well the candidate matches this job
  "overview": string,         // 2-4 sentences: strengths, relevant experience, gaps
  "matchedKeywords": string[] // key requirements from the job description evidenced in the resume
  "missingKeywords": string[] // important requirements from the job description absent from the resume
}}
Rules:
- score MUST be an integer 0-100.
- Ground everything in the resume text. Do not invent qualifications.
- Output raw JSON only."""


@dataclass
class ScoreResult:
    score: int
    overview: str
    raw_payload: dict[str, Any]
    model: str
    prompt_version: str


def _clamp_score(value: Any) -> int:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return 0


def _str(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


async def score_resume(
    *,
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    """Score a resume against a job using the Ollama hosted API.

    If the API key is missing (local dev without secrets), falls back to a
    deterministic keyword-match scorer so the pipeline stays demoable.
    """
    provider = OllamaChatProvider()
    if provider.is_configured():
        return await _score_with_llm(provider, resume_text, job_title, job_description)
    return _score_deterministic(resume_text, job_title, job_description)


async def _score_with_llm(
    provider: OllamaChatProvider,
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    user_prompt = USER_PROMPT.format(
        job_title=job_title,
        job_description=job_description or "Not provided.",
        resume_text=resume_text[:12000],
    )
    try:
        data = await provider.complete_json(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    except ChatProviderError:
        # graceful degradation per error-handling principles: fall back, never crash
        return _score_deterministic(resume_text, job_title, job_description)

    return ScoreResult(
        score=_clamp_score(data.get("score")),
        overview=_str(data.get("overview"), "No overview provided."),
        raw_payload=data,
        model=provider._model,
        prompt_version=PROMPT_VERSION,
    )


def _score_deterministic(
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    """Zero-dependency fallback: term-overlap matching when no Ollama key is set.

    Tokenizes the job description into keywords, counts how many appear in the
    resume, and produces a heuristic score + overview. Explicitly a fallback —
    the real scoring is the LLM path.
    """
    resume_lower = resume_text.lower()
    job_lower = job_description.lower() if job_description else job_title.lower()

    keywords = _extract_keywords(job_lower)
    if not keywords:
        return ScoreResult(
            score=50,
            overview="No job description was provided, so the score is a neutral estimate. "
            "Add a job description for a meaningful AI evaluation.",
            raw_payload={"fallback": True},
            model="deterministic-fallback",
            prompt_version=PROMPT_VERSION,
        )

    matched = [kw for kw in keywords if kw in resume_lower]
    missing = [kw for kw in keywords if kw not in resume_lower]
    score = round(100 * len(matched) / len(keywords))

    if score >= 70:
        overview = f"The resume matches {len(matched)} of {len(keywords)} key requirements for this role."
    elif score >= 40:
        overview = (
            f"The resume partially matches this role: {len(matched)} of {len(keywords)} "
            "key requirements were found, but important gaps remain."
        )
    else:
        overview = (
            f"The resume is a weak match: only {len(matched)} of {len(keywords)} key "
            "requirements were found. Significant gaps exist."
        )

    return ScoreResult(
        score=score,
        overview=overview,
        raw_payload={"fallback": True, "matchedKeywords": matched, "missingKeywords": missing},
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
