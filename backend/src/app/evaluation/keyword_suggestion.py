from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.evaluation.skills_taxonomy import normalize_skill
from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

PROMPT_VERSION = "keyword-suggestion-v1"

Tier = Literal["critical", "important", "nice_to_have"]
TIER_VALUES: tuple[Tier, ...] = ("critical", "important", "nice_to_have")

#: Fixed weight per tier — the only place the tier -> number mapping lives,
#: so the ratio can change without touching stored data (vacancies only
#: ever store the tier name, never a raw weight). See keyword_scoring.py
#: for where this is actually applied.
TIER_WEIGHTS: dict[Tier, int] = {"critical": 5, "important": 3, "nice_to_have": 1}

DEFAULT_SYSTEM_PROMPT = (
    "You extract screening keywords from a job posting for a hiring manager to "
    "review and adjust. You are not scoring a candidate — only identifying what "
    "to screen resumes for.\n\n"
    "Go beyond literal tool/technology names — infer the seniority level the "
    "title and description imply (e.g. junior/associate, mid-level, senior, "
    "staff/principal, or a people-manager/lead title) and let it shape which "
    "keywords you suggest and how you tier them:\n"
    "- Senior, staff, lead, or manager-level roles usually carry implicit "
    "expectations of leadership, mentoring, cross-functional communication, "
    "and stakeholder management even when the posting never spells them out — "
    "include those as keywords, tiered 'important' unless the posting states "
    "them as a hard requirement (then 'critical').\n"
    "- Junior, entry-level, or individual-contributor postings should stay "
    "focused on core technical fundamentals; don't invent leadership "
    "requirements a junior posting never implies.\n"
    "- Weigh other semantic context the literal wording won't spell out, too: "
    "a customer-facing role implies communication/empathy skills, a sales "
    "role implies negotiation/relationship-building, a regulated-industry "
    "role implies compliance awareness, and so on — reflect what the role "
    "actually demands, not just the nouns the posting happens to use.\n\n"
    "Respond with ONLY a single valid JSON object matching the schema in the "
    "user message. No markdown fences, no commentary."
)

USER_PROMPT = """Read the following job posting and extract the concrete skills, tools, \
qualifications, and experience the ideal candidate should have.

JOB TITLE: {title}

JOB DESCRIPTION:
{description}

Return a single JSON object with exactly this shape:
{{
  "keywords": [
    {{
      "keyword": string,      // a specific, concrete skill/tool/qualification — not a
                               // vague phrase. Prefer "Kubernetes" over "container
                               // orchestration experience"; prefer "5+ years of backend
                               // engineering" over "seniority".
      "tier": string          // one of "critical", "important", "nice_to_have" — your
                               // best guess from how the posting phrases it:
                               // "critical" for things stated as required/must-have/minimum,
                               // "important" for things stated as strongly preferred/should-have,
                               // "nice_to_have" for things stated as a bonus/plus/nice-to-have,
                               // or for skills merely mentioned without emphasis.
    }}
  ]
}}
Rules:
- 8-15 keywords is typical — enough to meaningfully screen against, not an exhaustive list.
- Most keywords should come directly from the posting's own content. You may also
  add a small number of level- or role-implied keywords (e.g. leadership for a
  Lead/Manager title, communication for a customer-facing role) when the title or
  description clearly calls for them, even if not explicitly named — but don't
  invent requirements the role doesn't plausibly need.
- Prefer distinct, specific keywords over near-duplicates (don't list both "Python" and "Python programming").
- Output raw JSON only."""


@dataclass
class SuggestedKeyword:
    keyword: str
    tier: Tier


@dataclass
class KeywordSuggestionResult:
    keywords: list[SuggestedKeyword]
    model: str
    prompt_version: str


def _normalize_tier(value: Any) -> Tier:
    """Coerce a raw tier string into a valid Tier, defaulting to the middle tier.

    A manager reviews and adjusts every suggestion before it's ever used for
    scoring, so an odd/missing tier from the model just needs a safe,
    unsurprising default — not perfect judgment.
    """
    if isinstance(value, str) and value.strip().lower() in TIER_VALUES:
        return value.strip().lower()  # type: ignore[return-value]
    return "important"


def _normalize_keyword(raw: str) -> str:
    """Canonicalize a suggested keyword against the skills taxonomy when recognized.

    Keeps the vacancy's keyword list using the same canonical spelling the
    resume-side matching already looks for (see skills_taxonomy.py) — a
    manager reviewing "kubernetes" rather than whatever casing/alias the
    model happened to output is also just more consistent to read.
    """
    canonical = normalize_skill(raw)
    return canonical if canonical is not None else raw.strip()


def _dedupe_keywords(keywords: list[SuggestedKeyword]) -> list[SuggestedKeyword]:
    """Drop keywords that normalized to the same canonical term, keeping the first (highest-tier-first order)."""
    seen: set[str] = set()
    result: list[SuggestedKeyword] = []
    for kw in keywords:
        key = kw.keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(kw)
    return result


async def suggest_keywords(
    title: str,
    description: str,
    *,
    api_base: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
) -> KeywordSuggestionResult:
    """Extract candidate screening keywords + a suggested tier from a job posting.

    The manager reviews, checks/unchecks, and adjusts every tier before the
    vacancy is posted — this is a starting point, not the final rubric.
    `system_prompt` defaults to DEFAULT_SYSTEM_PROMPT but is manager-editable
    via Settings (see capabilities/settings.py), same as the resume-review
    prompt. Raises ChatProviderError if no AI provider is configured or the
    call fails; there is no deterministic fallback (a keyword list a manager
    can't trust the source of isn't worth generating).
    """
    provider = OllamaChatProvider(api_base=api_base, model=model, api_key=api_key)
    if not provider.is_configured():
        raise ChatProviderError("No AI provider is configured.")

    data = await provider.complete_json(
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        user_prompt=USER_PROMPT.format(title=title, description=description or "Not provided."),
    )

    raw_keywords = data.get("keywords")
    keywords: list[SuggestedKeyword] = []
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            if not isinstance(item, dict):
                continue
            keyword = item.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                continue
            keywords.append(SuggestedKeyword(keyword=_normalize_keyword(keyword), tier=_normalize_tier(item.get("tier"))))

    # tier order (critical first) so a dedupe collision keeps the higher tier
    order = {tier: i for i, tier in enumerate(TIER_VALUES)}
    keywords.sort(key=lambda kw: order[kw.tier])
    keywords = _dedupe_keywords(keywords)

    return KeywordSuggestionResult(
        keywords=keywords,
        model=provider._model,
        prompt_version=PROMPT_VERSION,
    )
