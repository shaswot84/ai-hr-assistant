from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.evaluation.resume_structuring import StructuredResume
from app.evaluation.skills_taxonomy import find_skills_in_text, normalize_skill
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
{structured_context}
Return a single JSON object with exactly this shape:
{{
  "requirements": [                     // ONLY explicit must-haves stated in the job description
    {{
      "requirement": string,            // the must-have, as stated, e.g. "3+ years of Python experience"
      "met": boolean,                   // does this candidate clearly meet it, per the resume?
      "evidence": string                // what in the resume supports this verdict (or why it's missing)
    }}
    // Do NOT include "preferred"/"nice to have"/general skills here — only things
    // stated as required, minimum, must-have, or mandatory. Empty array if the job
    // description states no explicit hard requirements.
  ],
  "matchScore": number,                 // 0-100, overall fit for THIS job (soft ranking, independent of requirements)
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
- "requirements" is a hard gate: judge each conservatively — only mark "met": true when the resume clearly supports it.
- "weaknesses" must be specific gaps against THIS job's requirements, not generic writing critiques.
- "candidateProfile" fields must be copied verbatim from the resume text, never invented; use "" for anything not present.
- If verified structured data is provided above, use its total-years-of-experience figure for the "Experience Level" factor and for any years-of-experience requirement, instead of estimating your own from the raw text.
- Output raw JSON only."""


def _format_structured_context(structured: StructuredResume | None) -> str:
    """Render extracted structured facts as prompt context, or "" if none available.

    Keeps `score_resume` grounded in the deterministically-computed years of
    experience and parsed work/education history from the separate
    structuring step, rather than having it re-derive those facts itself
    from the raw resume text each time.
    """
    if structured is None or (not structured.work_experience and not structured.education):
        return ""

    lines = [
        "",
        (
            "VERIFIED STRUCTURED DATA (extracted separately from this resume — trust "
            "this over your own reading of the raw text for experience level and dates):"
        ),
        f"Total years of experience (computed from work history dates): {structured.total_years_experience:g}",
    ]
    if structured.work_experience:
        lines.append("Work history:")
        for entry in structured.work_experience:
            span = f"{entry.start_date or '?'} - {entry.end_date or '?'}"
            lines.append(f"- {entry.title or 'Unknown title'} at {entry.company or 'Unknown company'} ({span})")
    if structured.education:
        lines.append("Education:")
        for entry in structured.education:
            lines.append(
                f"- {entry.degree or 'Unknown degree'}, {entry.institution or 'Unknown institution'} "
                f"({entry.graduation_year or '?'})"
            )
    return "\n".join(lines)


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


_YEARS_REQUIREMENT_RE = re.compile(r"(\d+)\s*\+?\s*years?", re.IGNORECASE)

#: Recommendation forced whenever a candidate fails one or more hard
#: requirements — distinct from the score-band labels below "Weak Match"
#: so a manager can tell "didn't meet the bar" apart from "met the bar,
#: just isn't a great fit" at a glance, instead of both looking like a
#: merely-low fuzzy score.
DOES_NOT_MEET_REQUIREMENTS = "Does Not Meet Requirements"


def _requirements(value: Any) -> list[dict[str, Any]]:
    """Normalize the requirements list into [{requirement, met, evidence}]."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        requirement = _str(item.get("requirement"))
        if not requirement:
            continue
        result.append(
            {
                "requirement": requirement,
                "met": bool(item.get("met")),
                "evidence": _str(item.get("evidence")),
            }
        )
    return result


def _apply_deterministic_requirement_checks(
    requirements: list[dict[str, Any]], structured: StructuredResume | None
) -> list[dict[str, Any]]:
    """Override the LLM's own verdict on years-of-experience requirements with a deterministic check.

    Mirrors the reasoning in `resume_structuring`: a specific number
    ("3+ years") is exactly the kind of claim that shouldn't be trusted to
    the model's own arithmetic when a verified figure is available.
    """
    if structured is None:
        return requirements
    for req in requirements:
        match = _YEARS_REQUIREMENT_RE.search(req["requirement"])
        if match is None:
            continue
        required_years = int(match.group(1))
        met = structured.total_years_experience >= required_years
        req["met"] = met
        req["evidence"] = (
            f"Verified: {structured.total_years_experience:g} years of experience computed "
            f"from work history dates (requires {required_years}+)."
        )
    return requirements


def _reconcile_keywords_with_taxonomy(
    matched: list[str], missing: list[str], resume_text: str
) -> tuple[list[str], list[str]]:
    """Cross-check the model's missingKeywords against known skill aliases actually in the resume.

    The model can mark "Kubernetes" missing when the resume only says "K8s"
    — same skill, different spelling, easy to miss in a single free-text
    pass. Anything the skills taxonomy recognizes gets deterministically
    re-checked here; keywords outside the taxonomy are left as the model
    judged them (unchanged behavior for terms we don't have curated).
    """
    resume_skills = find_skills_in_text(resume_text)
    corrected_matched = list(matched)
    still_missing = []
    for keyword in missing:
        canonical = normalize_skill(keyword)
        if canonical is not None and canonical in resume_skills:
            if keyword not in corrected_matched:
                corrected_matched.append(keyword)
        else:
            still_missing.append(keyword)
    return corrected_matched, still_missing


def _normalize_review(
    data: dict[str, Any], structured: StructuredResume | None = None, resume_text: str = ""
) -> dict[str, Any]:
    """Coerce a raw model payload into a well-typed, defensively-parsed screening object.

    Missing/odd-shaped fields fall back to empty/safe defaults so the UI never
    breaks on a partially malformed model response. Hard requirements are
    checked first: a candidate who fails one is given the
    `DOES_NOT_MEET_REQUIREMENTS` recommendation regardless of matchScore, so
    a categorical gate isn't blended into the fuzzy 0-100 ranking.
    """
    score = _clamp_score(data.get("matchScore"))
    recommendation = _str(data.get("recommendation")) or _recommendation_for(score)

    requirements = _apply_deterministic_requirement_checks(_requirements(data.get("requirements")), structured)
    requirements_met = all(r["met"] for r in requirements)
    if not requirements_met:
        recommendation = DOES_NOT_MEET_REQUIREMENTS

    matched_keywords, missing_keywords = _reconcile_keywords_with_taxonomy(
        _str_list(data.get("matchedKeywords")), _str_list(data.get("missingKeywords")), resume_text
    )

    return {
        "requirements": requirements,
        "requirementsMet": requirements_met,
        "matchScore": score,
        "recommendation": recommendation,
        "summary": _str(data.get("summary"), "No summary provided."),
        "scoreFactors": _score_factors(data.get("scoreFactors")),
        "strengths": _str_list(data.get("strengths")),
        "weaknesses": _str_list(data.get("weaknesses")),
        "matchedKeywords": matched_keywords,
        "missingKeywords": missing_keywords,
        "candidateProfile": _candidate_profile(data.get("candidateProfile")),
    }


async def score_resume(
    *,
    resume_text: str,
    job_title: str,
    job_description: str,
    structured: StructuredResume | None = None,
    system_prompt: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> ScoreResult:
    """Screen a resume against a job using the Ollama hosted API.

    ``structured`` is the separately-extracted work/education/skills data
    (see `evaluation.resume_structuring`); when given, its computed years of
    experience and parsed history ground the "Experience Level" factor
    instead of the model re-deriving those facts from raw text each time.
    ``system_prompt`` lets a manager override the model instructions (stored in
    settings); when None, the default constant is used. ``api_base``/``model``/
    ``api_key`` are the manager-editable LLM connection settings (also stored
    in settings); when None, the .env-configured defaults are used. If the
    resolved API key is missing (local dev without secrets), falls back to a
    deterministic keyword-match scorer so the pipeline stays demoable.
    """
    provider = OllamaChatProvider(api_base=api_base, model=model, api_key=api_key)
    if provider.is_configured():
        return await _score_with_llm(
            provider, resume_text, job_title, job_description, structured, system_prompt
        )
    return _score_deterministic(resume_text, job_title, job_description)


async def _score_with_llm(
    provider: OllamaChatProvider,
    resume_text: str,
    job_title: str,
    job_description: str,
    structured: StructuredResume | None,
    system_prompt: str | None,
) -> ScoreResult:
    """Screen the resume via the Ollama chat provider, falling back to the deterministic scorer."""
    user_prompt = USER_PROMPT.format(
        job_title=job_title,
        job_description=job_description or "Not provided.",
        resume_text=resume_text[:12000],
        structured_context=_format_structured_context(structured),
    )
    try:
        data = await provider.complete_json(
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except ChatProviderError:
        # graceful degradation per error-handling principles: fall back, never crash
        return _score_deterministic(resume_text, job_title, job_description)

    review = _normalize_review(data, structured, resume_text)
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


def _keyword_present_in_resume(keyword: str, resume_lower: str, resume_skills: set[str]) -> bool:
    """Check a job keyword against the resume, alias-aware for recognized skills.

    A keyword the skills taxonomy recognizes (e.g. "Kubernetes") matches if
    *any* known variation is in the resume (e.g. "K8s"), not only the exact
    literal string — the plain substring check only applies to keywords
    outside the taxonomy, where no alias information exists.
    """
    canonical = normalize_skill(keyword)
    if canonical is not None:
        return canonical in resume_skills
    return keyword in resume_lower


def _score_deterministic(
    resume_text: str,
    job_title: str,
    job_description: str,
) -> ScoreResult:
    """Zero-dependency fallback: taxonomy-aware term-overlap matching when no Ollama key is set.

    Tokenizes the job description into keywords, counts how many appear in
    the resume (recognized skills matched by any known alias, everything
    else by plain substring), and produces a heuristic score. Explicitly a
    fallback — the real screening (score factors, strengths/weaknesses) is
    the LLM path; this only ever produces a single "Keyword Coverage" factor.
    """
    resume_lower = resume_text.lower()
    job_lower = job_description.lower() if job_description else job_title.lower()
    candidate_profile = _extract_contact_profile(resume_text)
    resume_skills = find_skills_in_text(resume_text)

    # Single-word tokenization alone can't catch multi-word skills (e.g.
    # "machine learning", "project management") since it never joins two
    # tokens back together — merge in taxonomy-recognized phrases found
    # directly in the job text so those aren't silently invisible.
    keywords = sorted(set(_extract_keywords(job_lower)) | find_skills_in_text(job_lower))
    if not keywords:
        summary = (
            "No job description was provided, so this is a neutral estimate. "
            "Add a job description for a meaningful AI screening."
        )
        review = {
            "requirements": [],
            "requirementsMet": True,
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

    matched = [kw for kw in keywords if _keyword_present_in_resume(kw, resume_lower, resume_skills)]
    missing = [kw for kw in keywords if not _keyword_present_in_resume(kw, resume_lower, resume_skills)]
    score = round(100 * len(matched) / len(keywords))

    summary = (
        f"The resume shares {len(matched)} of {len(keywords)} key requirements with the job "
        "(keyword-based fallback, not a full AI screening)."
    )
    review = {
        "requirements": [],
        "requirementsMet": True,
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
