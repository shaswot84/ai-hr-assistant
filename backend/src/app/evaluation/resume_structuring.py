from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from string import Template
from typing import Any

from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

PROMPT_VERSION = "resume-structuring-v1"

#: Extraction-only prompt: pulls facts as literally written on the resume.
#: Deliberately does NOT ask the model to compute derived numbers (like
#: total years of experience) — that's calculated deterministically in
#: Python from the extracted date strings instead of trusted to the LLM's
#: arithmetic, so it's auditable and reproducible.
DEFAULT_SYSTEM_PROMPT = (
    "You extract structured facts from a resume. You are not evaluating or "
    "scoring the candidate — only pulling out what is literally written. "
    "Copy dates, titles, and names verbatim; do not compute durations, "
    "totals, or summaries. Respond with ONLY a single valid JSON object "
    "matching the schema in the user message. No markdown fences, no "
    "commentary."
)

#: Task template for the extraction call. Uses `$name` placeholders (stdlib
#: `string.Template`), not `str.format()` — manager-editable (see Settings)
#: and full of literal JSON braces for the response schema; `$name`
#: substitution never touches `{`/`}`, so an edit can't break on an
#: unescaped brace the way `.format()` would. Rendered via `safe_substitute`
#: (see `extract_structured_resume`), so a missing/renamed placeholder
#: degrades gracefully instead of raising.
USER_PROMPT = """Extract structured facts from the following resume text.

RESUME TEXT (raw-extracted, may have imperfect spacing/line breaks):
$resume_text

Return a single JSON object with exactly this shape:
{
  "workExperience": [
    {
      "title": string,       // job title as written
      "company": string,     // employer name as written
      "startDate": string,   // as written, e.g. "Jan 2021", "2021"; "" if unclear
      "endDate": string      // as written, e.g. "2024", "Present"; "" if unclear
    }
  ],
  "education": [
    {
      "degree": string,          // e.g. "B.S. Computer Science"; "" if unclear
      "institution": string,     // "" if unclear
      "graduationYear": string   // as written, e.g. "2019"; "" if unclear
    }
  ],
  "skills": string[]        // individual skills/technologies listed on the resume
}
Rules:
- List every distinct role found under work/employment history, most recent first.
- Do not invent entries, dates, or skills not present in the text.
- Output raw JSON only."""


@dataclass
class WorkExperienceEntry:
    """One work-history entry, dates kept as written plus a best-effort parsed year."""

    title: str
    company: str
    start_date: str
    end_date: str
    start_year: int | None = None
    end_year: int | None = None
    is_current: bool = False


@dataclass
class EducationEntry:
    degree: str
    institution: str
    graduation_year: int | None = None


@dataclass
class StructuredResume:
    """Structured facts pulled from a resume, separate from any job-fit scoring.

    `total_years_experience` is always computed in Python from the parsed
    `start_year`/`end_year` fields (career span: earliest start to latest
    end/present), never asked of the LLM — see module docstring rationale.
    """

    work_experience: list[WorkExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    total_years_experience: float = 0.0
    model: str = "none"
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_YEAR_RE = re.compile(r"(19|20)\d{2}")
_CURRENT_RE = re.compile(r"present|current|now", re.IGNORECASE)


def _parse_year(date_str: str) -> int | None:
    """Best-effort pull of a 4-digit year out of a free-form date string."""
    match = _YEAR_RE.search(date_str or "")
    return int(match.group(0)) if match else None


def _is_current(date_str: str) -> bool:
    return bool(_CURRENT_RE.search(date_str or ""))


def _compute_total_years(work_experience: list[WorkExperienceEntry]) -> float:
    """Career span (earliest start to latest end/present) in years, not summed job durations.

    Summing each entry's duration would double-count overlapping/concurrent
    roles; using the overall span is the simpler, standard estimate and
    avoids that. Entries with no resolvable start year are ignored.
    """
    starts = [e.start_year for e in work_experience if e.start_year is not None]
    if not starts:
        return 0.0
    current_year = datetime.now(UTC).year
    ends = [
        current_year if e.is_current or e.end_year is None else e.end_year
        for e in work_experience
        if e.start_year is not None
    ]
    span = max(ends) - min(starts)
    return float(max(span, 0))


def _str(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _parse_work_experience(value: Any) -> list[WorkExperienceEntry]:
    entries: list[WorkExperienceEntry] = []
    if not isinstance(value, list):
        return entries
    for item in value:
        if not isinstance(item, dict):
            continue
        start_date = _str(item.get("startDate"))
        end_date = _str(item.get("endDate"))
        entries.append(
            WorkExperienceEntry(
                title=_str(item.get("title")),
                company=_str(item.get("company")),
                start_date=start_date,
                end_date=end_date,
                start_year=_parse_year(start_date),
                end_year=_parse_year(end_date),
                is_current=_is_current(end_date),
            )
        )
    return entries


def _parse_education(value: Any) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    if not isinstance(value, list):
        return entries
    for item in value:
        if not isinstance(item, dict):
            continue
        entries.append(
            EducationEntry(
                degree=_str(item.get("degree")),
                institution=_str(item.get("institution")),
                graduation_year=_parse_year(_str(item.get("graduationYear"))),
            )
        )
    return entries


async def extract_structured_resume(
    resume_text: str,
    *,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> StructuredResume:
    """Pull structured work history, education, and skills out of a resume.

    Runs as its own step, before job-fit scoring, so the scoring prompt can
    be grounded in verified structured facts (e.g. a deterministically
    computed years-of-experience) instead of re-guessing everything from
    raw text in one shot. ``system_prompt``/``user_prompt`` let a manager
    override the model instructions (stored in settings); when None, the
    default constants are used.

    Raises `ChatProviderError` if no AI provider is configured, or if the
    provider call fails — there is no deterministic fallback; a rough
    year-span guess with no titles, companies, or degrees is not an honest
    substitute for real extraction.
    """
    provider = OllamaChatProvider(api_base=api_base, model=model, api_key=api_key)
    if not provider.is_configured():
        raise ChatProviderError("No AI provider is configured.")

    # safe_substitute (not substitute): a manager's edited template that drops
    # or misspells $resume_text degrades to the literal text instead of
    # raising and failing every evaluation.
    rendered_user_prompt = Template(user_prompt or USER_PROMPT).safe_substitute(
        resume_text=resume_text[:12000]
    )
    data = await provider.complete_json(
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        user_prompt=rendered_user_prompt,
    )

    work_experience = _parse_work_experience(data.get("workExperience"))
    education = _parse_education(data.get("education"))
    skills = _str_list(data.get("skills"))

    return StructuredResume(
        work_experience=work_experience,
        education=education,
        skills=skills,
        total_years_experience=_compute_total_years(work_experience),
        model=provider._model,
        prompt_version=PROMPT_VERSION,
    )
