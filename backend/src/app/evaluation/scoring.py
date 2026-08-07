from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

PROMPT_VERSION = "recruitment-screen-v1"

#: Default system prompt instructing the model how to behave. Managers can
#: override this at runtime through the Settings page; that override is stored
#: in the ``app_setting`` table and passed in via ``score_resume``.
#:
#: This is an ATS-style screening assistant, not a resume-writing coach: the
#: job is to tell a hiring manager whether this candidate matches this role
#: and why, not to critique the resume's writing quality.
DEFAULT_SYSTEM_PROMPT = (
    "You are an ATS-style resume screener helping a hiring manager decide whether a "
    "candidate matches a specific job opening. You are not a resume-writing coach — "
    "do not critique writing style, formatting, or phrasing. Judge fit only: skills, "
    "experience level, and relevance to the role. Be grounded only in the resume text "
    "provided — never invent experience the candidate does not have. Respond with ONLY "
    "a single valid JSON object matching the schema in the user message. No markdown "
    "fences, no commentary."
)

USER_PROMPT = """Screen the following resume against a target job opening, the way an ATS + recruiter would.

TARGET JOB:
Title: {job_title}
Description:
{job_description}

RESUME TEXT (raw-extracted, may have imperfect spacing/line breaks — look past formatting artifacts to the content):
{resume_text}

Return a single JSON object with exactly this shape:
{{
  "matchScore": number,                 // 0-100, overall fit for THIS job
  "recommendation": string,             // one of: "Strong Match", "Good Match", "Possible Match", "Weak Match"
  "summary": string,                    // 2-3 sentences: does this candidate match the role, and why
  "scoreFactors": [                     // 3-5 factors that explain the score, each independently
    {{"factor": string, "score": number, "note": string}}
    // e.g. {{"factor": "Skills Match", "score": 90, "note": "Has 4 of 5 required technologies"}}
    // cover at least: Skills Match, Experience Level, Domain/Role Relevance
  ],
  "strengths": string[],                // 2-4 concrete reasons this candidate fits (pros)
  "weaknesses": string[],               // 2-4 concrete gaps vs the job requirements (cons); empty if none
  "matchedKeywords": string[],          // job requirements evidenced in the resume
  "missingKeywords": string[],          // important job requirements absent from the resume
  "candidateProfile": {{                // identity/contact info read directly off the resume
    "name": string,                     // candidate's full name as written on the resume
    "email": string,                    // contact email found on the resume; "" if none
    "phone": string,                    // contact phone number found on the resume; "" if none
    "location": string,                 // city/region found on the resume; "" if none
    "headline": string                  // short role/seniority summary, e.g. "Senior Backend Engineer, 7 yrs"
  }}
}}
Rules:
- Ground every claim in the resume text. Do not fabricate skills or experience.
- "weaknesses" must be specific gaps against THIS job's requirements, not generic writing critiques.
- "candidateProfile" fields must be copied verbatim from the resume text, never invented; use "" for anything not present.
- Output raw JSON only."""


@dataclass
class ScoreResult:
    """Structured outcome of a resume-vs-job screening.

    ``score``/``overview`` are the compact columns; the full structured
    screening (score factors, strengths/weaknesses) is kept in
    ``raw_payload`` for the manager-facing review UI.
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


def _recommendation_for(score: int) -> str:
    """Derive a recommendation label from a 0-100 score (used by both LLM and fallback paths)."""
    if score >= 80:
        return "Strong Match"
    if score >= 60:
        return "Good Match"
    if score >= 40:
        return "Possible Match"
    return "Weak Match"


def _score_factors(value: Any) -> list[dict[str, Any]]:
    """Normalize the scoreFactors list into [{factor, score, note}]."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        factor = _str(item.get("factor"))
        if not factor:
            continue
        result.append(
            {
                "factor": factor,
                "score": _clamp_score(item.get("score")),
                "note": _str(item.get("note")),
            }
        )
    return result


def _candidate_profile(value: Any) -> dict[str, str]:
    """Normalize the candidateProfile object into {name, email, phone, location, headline}."""
    obj = value if isinstance(value, dict) else {}
    return {
        "name": _str(obj.get("name")),
        "email": _str(obj.get("email")),
        "phone": _str(obj.get("phone")),
        "location": _str(obj.get("location")),
        "headline": _str(obj.get("headline")),
    }


def _normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw model payload into a well-typed, defensively-parsed screening object.

    Missing/odd-shaped fields fall back to empty/safe defaults so the UI never
    breaks on a partially malformed model response.
    """
    score = _clamp_score(data.get("matchScore"))
    recommendation = _str(data.get("recommendation")) or _recommendation_for(score)

    return {
        "matchScore": score,
        "recommendation": recommendation,
        "summary": _str(data.get("summary"), "No summary provided."),
        "scoreFactors": _score_factors(data.get("scoreFactors")),
        "strengths": _str_list(data.get("strengths")),
        "weaknesses": _str_list(data.get("weaknesses")),
        "matchedKeywords": _str_list(data.get("matchedKeywords")),
        "missingKeywords": _str_list(data.get("missingKeywords")),
        "candidateProfile": _candidate_profile(data.get("candidateProfile")),
    }


async def score_resume(
    *,
    resume_text: str,
    job_title: str,
    job_description: str,
    system_prompt: str | None = None,
) -> ScoreResult:
    """Screen a resume against a job using the Ollama hosted API.

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
    """Screen the resume via the Ollama chat provider, falling back to the deterministic scorer."""
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
        score=review["matchScore"],
        overview=review["summary"],
        raw_payload=review,
        model=provider._model,
        prompt_version=PROMPT_VERSION,
    )


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d .()-]{8,}\d)")


def _extract_contact_profile(resume_text: str) -> dict[str, str]:
    """Best-effort regex extraction of contact info for the non-LLM fallback path.

    No LLM available here, so this only pulls what's mechanically findable
    (email, phone, a guessed name from the first line) — far cruder than the
    LLM path, but keeps the candidate profile section populated when the
    deterministic scorer is in use.
    """
    email_match = _EMAIL_RE.search(resume_text)
    phone_match = _PHONE_RE.search(resume_text)

    name = ""
    for line in resume_text.splitlines():
        candidate = line.strip()
        if 2 <= len(candidate) <= 60 and not _EMAIL_RE.search(candidate) and not any(
            ch.isdigit() for ch in candidate
        ):
            name = candidate
            break

    return {
        "name": name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0).strip() if phone_match else "",
        "location": "",
        "headline": "",
    }


def _score_deterministic(
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    """Zero-dependency fallback: term-overlap matching when no Ollama key is set.

    Tokenizes the job description into keywords, counts how many appear in the
    resume, and produces a heuristic score. Explicitly a fallback — the real
    screening (score factors, strengths/weaknesses) is the LLM path; this only
    ever produces a single "Keyword Coverage" factor.
    """
    resume_lower = resume_text.lower()
    job_lower = job_description.lower() if job_description else job_title.lower()
    candidate_profile = _extract_contact_profile(resume_text)

    keywords = _extract_keywords(job_lower)
    if not keywords:
        summary = (
            "No job description was provided, so this is a neutral estimate. "
            "Add a job description for a meaningful AI screening."
        )
        review = {
            "matchScore": 50,
            "recommendation": _recommendation_for(50),
            "summary": summary,
            "scoreFactors": [
                {"factor": "Keyword Coverage", "score": 50, "note": "No job description to compare against."}
            ],
            "strengths": [],
            "weaknesses": [],
            "matchedKeywords": [],
            "missingKeywords": [],
            "candidateProfile": candidate_profile,
        }
        return ScoreResult(
            score=50,
            overview=summary,
            raw_payload=review,
            model="deterministic-fallback",
            prompt_version=PROMPT_VERSION,
        )

    matched = [kw for kw in keywords if kw in resume_lower]
    missing = [kw for kw in keywords if kw not in resume_lower]
    score = round(100 * len(matched) / len(keywords))

    summary = (
        f"The resume shares {len(matched)} of {len(keywords)} key requirements with the job "
        "(keyword-based fallback, not a full AI screening)."
    )
    review = {
        "matchScore": score,
        "recommendation": _recommendation_for(score),
        "summary": summary,
        "scoreFactors": [
            {
                "factor": "Keyword Coverage",
                "score": score,
                "note": f"{len(matched)} of {len(keywords)} job keywords found in the resume.",
            }
        ],
        "strengths": [],
        "weaknesses": [],
        "matchedKeywords": matched,
        "missingKeywords": missing,
        "candidateProfile": candidate_profile,
    }

    return ScoreResult(
        score=score,
        overview=summary,
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
