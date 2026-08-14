from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.evaluation.keyword_suggestion import TIER_WEIGHTS
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
{scoring_keywords_context}
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
  "recommendation": string,             // one of: "Strong Match", "Good Match", "Possible Match", "Weak Match"
  "summary": string,                    // 2-3 sentences: does this candidate match the role, and why
  "keyFactors": [                       // 3-5 qualitative factors that explain the recommendation
    {{"factor": string, "note": string}}
    // e.g. {{"factor": "Skills Match", "note": "Has 4 of 5 required technologies"}}
    // cover at least: Skills Match, Experience Level, Domain/Role Relevance
    // Describe each in words only — no numeric scores, this is a qualitative read.
  ],
  "strengths": string[],                // 2-4 concrete reasons this candidate fits (pros)
  "weaknesses": string[],               // 2-4 concrete gaps vs the job requirements (cons); empty if none
  "matchedKeywords": string[],          // job requirements evidenced in the resume
  "missingKeywords": string[],          // important job requirements absent from the resume
  "keywordMatches": [                   // ONLY for the SCORING KEYWORDS listed above, if any were given
    {{"keyword": string, "present": boolean, "evidence": string}}
    // exactly one entry per keyword in the SCORING KEYWORDS list, same spelling,
    // judged independently from "requirements"/"matchedKeywords" above. Empty
    // array if no SCORING KEYWORDS section was given.
  ],
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


def _format_scoring_keywords_section(scoring_keywords: list[dict[str, Any]] | None) -> str:
    """Render the vacancy's manager-configured scoring keywords as prompt context, or "" if none.

    Deliberately doesn't mention tier/weight to the model — the model's only
    job is judging presence (yes/no + evidence) per keyword; the tier ->
    weight math that turns that into a score happens entirely in Python
    (see `_compute_keyword_score`), never left to the model to compute.
    """
    if not scoring_keywords:
        return ""
    lines = [
        "",
        (
            "SCORING KEYWORDS (the hiring manager configured these to screen this "
            'resume against — judge each independently in "keywordMatches"):'
        ),
    ]
    lines.extend(f"- {kw['keyword']}" for kw in scoring_keywords)
    return "\n".join(lines)


@dataclass
class ScoreResult:
    """Structured outcome of a resume-vs-job screening.

    ``overview`` is the compact summary column; the full structured
    screening (requirements, key factors, strengths/weaknesses) is kept in
    ``raw_payload`` for the manager-facing review UI. There is deliberately
    no numeric score here — see `DEFAULT_SYSTEM_PROMPT` / `USER_PROMPT`: an
    LLM asked for "a number" with no rubric produces digits that look
    precise but aren't comparable across candidates.
    """

    overview: str
    raw_payload: dict[str, Any]
    model: str
    prompt_version: str
    #: 0-100, deterministically computed from the vacancy's weighted scoring
    #: keywords (see `_compute_keyword_score`) — None when the vacancy has no
    #: scoring keywords configured. Unlike the old `score` field this class
    #: used to have, every point here is auditable: a fixed formula over the
    #: model's per-keyword yes/no judgments, not an invented number.
    keyword_score: int | None = None


#: Recommendation used when the model's response omits one (defensive
#: parsing only — there is no score to derive a label from anymore).
DEFAULT_RECOMMENDATION = "Needs Review"


def _str(value: Any, fallback: str = "") -> str:
    """Return `value` if it is a string, otherwise the given fallback."""
    return value if isinstance(value, str) else fallback


def _str_list(value: Any) -> list[str]:
    """Return the list of strings contained in `value` (empty list for non-list inputs)."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _key_factors(value: Any) -> list[dict[str, Any]]:
    """Normalize the keyFactors list into [{factor, note}] — qualitative, no numbers."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        factor = _str(item.get("factor"))
        if not factor:
            continue
        result.append({"factor": factor, "note": _str(item.get("note"))})
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
#: requirements — distinct from the model's own free-text recommendation
#: label so a manager can tell "didn't meet the bar" apart from "met the
#: bar, just isn't a great fit" at a glance.
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


def _keyword_matches(value: Any) -> list[dict[str, Any]]:
    """Normalize the keywordMatches list into [{keyword, present, evidence}]."""
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        keyword = _str(item.get("keyword"))
        if not keyword:
            continue
        result.append(
            {
                "keyword": keyword,
                "present": bool(item.get("present")),
                "evidence": _str(item.get("evidence")),
            }
        )
    return result


def _reconcile_keyword_matches_with_taxonomy(
    matches: list[dict[str, Any]], resume_text: str
) -> list[dict[str, Any]]:
    """Cross-check keywords the model marked absent against known skill aliases in the resume.

    Same reasoning as `_reconcile_keywords_with_taxonomy`: the model can say
    "Kubernetes" is missing when the resume only says "K8s". This directly
    affects the deterministic score, so a taxonomy-recognized alias match
    overrides the model's own verdict rather than just being a display fix.
    """
    resume_skills = find_skills_in_text(resume_text)
    reconciled: list[dict[str, Any]] = []
    for match in matches:
        if not match["present"]:
            canonical = normalize_skill(match["keyword"])
            if canonical is not None and canonical in resume_skills:
                match = {
                    **match,
                    "present": True,
                    "evidence": f"Verified: resume mentions a recognized alias of {canonical}.",
                }
        reconciled.append(match)
    return reconciled


def _compute_keyword_score(
    keyword_matches: list[dict[str, Any]], scoring_keywords: list[dict[str, Any]] | None
) -> int | None:
    """Deterministically compute 0-100 from tier weights, never left to the model to invent.

    score = (sum of tier weights for matched, checked keywords) / (sum of
    tier weights for all checked keywords) * 100. Tiers come from the
    vacancy's own configuration (`scoring_keywords`), not from anything the
    model echoes back — the model only supplies presence/evidence per
    keyword. A configured keyword the model's response doesn't mention at
    all is treated as not matched (the conservative default), not skipped.
    """
    if not scoring_keywords:
        return None
    tier_by_keyword = {kw["keyword"]: kw.get("tier", "important") for kw in scoring_keywords}
    total_weight = sum(TIER_WEIGHTS.get(tier, TIER_WEIGHTS["important"]) for tier in tier_by_keyword.values())
    if total_weight == 0:
        return None
    present_keywords = {m["keyword"] for m in keyword_matches if m["present"]}
    matched_weight = sum(
        TIER_WEIGHTS.get(tier, TIER_WEIGHTS["important"])
        for keyword, tier in tier_by_keyword.items()
        if keyword in present_keywords
    )
    return round(100 * matched_weight / total_weight)


def _normalize_review(
    data: dict[str, Any],
    structured: StructuredResume | None = None,
    resume_text: str = "",
    scoring_keywords: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Coerce a raw model payload into a well-typed, defensively-parsed screening object.

    Missing/odd-shaped fields fall back to empty/safe defaults so the UI never
    breaks on a partially malformed model response. Hard requirements are
    checked first: a candidate who fails one is given the
    `DOES_NOT_MEET_REQUIREMENTS` recommendation regardless of what the model
    itself proposed, so a categorical gate isn't blended into a fuzzy label.
    """
    recommendation = _str(data.get("recommendation")) or DEFAULT_RECOMMENDATION

    requirements = _apply_deterministic_requirement_checks(_requirements(data.get("requirements")), structured)
    requirements_met = all(r["met"] for r in requirements)
    if not requirements_met:
        recommendation = DOES_NOT_MEET_REQUIREMENTS

    matched_keywords, missing_keywords = _reconcile_keywords_with_taxonomy(
        _str_list(data.get("matchedKeywords")), _str_list(data.get("missingKeywords")), resume_text
    )

    keyword_matches = _reconcile_keyword_matches_with_taxonomy(
        _keyword_matches(data.get("keywordMatches")), resume_text
    )
    keyword_score = _compute_keyword_score(keyword_matches, scoring_keywords)

    return {
        "requirements": requirements,
        "requirementsMet": requirements_met,
        "recommendation": recommendation,
        "summary": _str(data.get("summary"), "No summary provided."),
        "keyFactors": _key_factors(data.get("keyFactors")),
        "strengths": _str_list(data.get("strengths")),
        "weaknesses": _str_list(data.get("weaknesses")),
        "matchedKeywords": matched_keywords,
        "missingKeywords": missing_keywords,
        "keywordMatches": keyword_matches,
        "keywordScore": keyword_score,
        "candidateProfile": _candidate_profile(data.get("candidateProfile")),
    }


async def score_resume(
    *,
    resume_text: str,
    job_title: str,
    job_description: str,
    structured: StructuredResume | None = None,
    scoring_keywords: list[dict[str, Any]] | None = None,
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
    ``scoring_keywords`` is the vacancy's manager-configured keyword/tier
    list; when given, the model additionally judges per-keyword presence and
    `ScoreResult.keyword_score` is computed deterministically from it (see
    `_compute_keyword_score`) — None when not given. ``system_prompt`` lets a
    manager override the model instructions (stored in settings); when None,
    the default constant is used. ``api_base``/``model``/``api_key`` are the
    manager-editable LLM connection settings (also stored in settings); when
    None, the .env-configured defaults are used.

    Raises `ChatProviderError` if no AI provider is configured, or if the
    provider call fails — the caller is responsible for recording that as a
    failed evaluation rather than silently degrading to a lower-quality
    guess (there is no deterministic fallback; a keyword-overlap score is
    not an honest substitute for an actual screening).
    """
    provider = OllamaChatProvider(api_base=api_base, model=model, api_key=api_key)
    if not provider.is_configured():
        raise ChatProviderError("No AI provider is configured.")
    return await _score_with_llm(
        provider, resume_text, job_title, job_description, structured, scoring_keywords, system_prompt
    )


async def _score_with_llm(
    provider: OllamaChatProvider,
    resume_text: str,
    job_title: str,
    job_description: str,
    structured: StructuredResume | None,
    scoring_keywords: list[dict[str, Any]] | None,
    system_prompt: str | None,
) -> ScoreResult:
    """Screen the resume via the Ollama chat provider. Raises `ChatProviderError` on failure."""
    user_prompt = USER_PROMPT.format(
        job_title=job_title,
        job_description=job_description or "Not provided.",
        resume_text=resume_text[:12000],
        structured_context=_format_structured_context(structured),
        scoring_keywords_context=_format_scoring_keywords_section(scoring_keywords),
    )
    data = await provider.complete_json(
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    review = _normalize_review(data, structured, resume_text, scoring_keywords)
    return ScoreResult(
        overview=review["summary"],
        raw_payload=review,
        model=provider._model,
        prompt_version=PROMPT_VERSION,
        keyword_score=review["keywordScore"],
    )
