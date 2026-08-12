from __future__ import annotations

import re

#: Canonical skill name -> known aliases/variations (all lowercase). The
#: canonical name is matched automatically; aliases only need the *other*
#: spellings (e.g. "kubernetes" doesn't need to list "kubernetes" itself).
#: Deliberately a curated, extensible starting set focused on common
#: software/data roles (the dominant case in this recruitment pipeline)
#: plus a handful of general business/professional terms — not an
#: exhaustive industry-wide taxonomy.
SKILL_ALIASES: dict[str, list[str]] = {
    # Languages
    "javascript": ["js"],
    "typescript": ["ts"],
    "python": [],
    "java": [],
    "c++": ["cpp"],
    "c#": ["csharp", "c sharp"],
    "golang": ["go"],
    "ruby": [],
    "php": [],
    "swift": [],
    "kotlin": [],
    "rust": [],
    "sql": [],
    "html": ["html5"],
    "css": ["css3"],
    # Frameworks / libraries
    "react": ["react.js", "reactjs"],
    "angular": [],
    "vue": ["vue.js", "vuejs"],
    "next.js": ["nextjs", "next"],
    "django": [],
    "fastapi": [],
    "flask": [],
    "spring": ["spring boot"],
    "ruby on rails": ["rails"],
    "express": ["express.js", "expressjs"],
    ".net": ["dotnet"],
    "node.js": ["nodejs", "node"],
    # Databases
    "postgresql": ["postgres"],
    "mysql": [],
    "mongodb": ["mongo"],
    "redis": [],
    "sql server": ["mssql"],
    "sqlite": [],
    "oracle": ["oracle db"],
    "elasticsearch": ["elastic search"],
    # Infra / cloud / devops
    "aws": ["amazon web services"],
    "azure": ["microsoft azure"],
    "gcp": ["google cloud platform", "google cloud"],
    "docker": [],
    "kubernetes": ["k8s"],
    "terraform": [],
    "jenkins": [],
    "continuous integration": ["ci/cd", "ci cd", "cicd", "ci"],
    "ansible": [],
    "linux": [],
    "nginx": [],
    # Data / ML
    "machine learning": ["ml"],
    "artificial intelligence": ["ai"],
    "pandas": [],
    "numpy": [],
    "tensorflow": [],
    "pytorch": [],
    "scikit-learn": ["sklearn"],
    "tableau": [],
    "looker": [],
    "power bi": ["powerbi"],
    "excel": ["microsoft excel", "ms excel"],
    "a/b testing": ["ab testing", "a b testing"],
    # Tools
    "git": [],
    "github": [],
    "gitlab": [],
    "jira": [],
    "figma": [],
    "slack": [],
    "confluence": [],
    "zendesk": [],
    "intercom": [],
    "salesforce": [],
    "google analytics": ["ga4", "ga"],
    "hris": ["human resources information system"],
    # General/business skills
    "project management": [],
    "product management": [],
    "agile": [],
    "scrum": [],
    "communication": [],
    "leadership": [],
    "recruitment": ["recruiting", "talent acquisition"],
    "onboarding": [],
    "budget management": [],
}


def _build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in SKILL_ALIASES.items():
        index[canonical] = canonical
        for alias in aliases:
            index[alias] = canonical
    return index


_ALIAS_INDEX = _build_alias_index()


def _boundary_pattern(term: str) -> re.Pattern[str]:
    """A word-boundary pattern that also works for terms with symbols (c++, c#, ci/cd).

    Plain `\\b` doesn't reliably bound tokens containing `+`, `#`, or `/`,
    so this checks the surrounding characters aren't alphanumeric instead.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", re.IGNORECASE)


_TERM_PATTERNS = {term: _boundary_pattern(term) for term in _ALIAS_INDEX}


def normalize_skill(text: str) -> str | None:
    """Return the canonical skill name for a raw skill string, or None if unrecognized."""
    return _ALIAS_INDEX.get(text.strip().lower())


def find_skills_in_text(text: str) -> set[str]:
    """Return the set of canonical skill names found anywhere in `text`.

    Matches any known alias, not just the canonical spelling — e.g. a
    resume containing "K8s" is recognized as the "kubernetes" skill.
    """
    found: set[str] = set()
    for term, pattern in _TERM_PATTERNS.items():
        if pattern.search(text):
            found.add(_ALIAS_INDEX[term])
    return found
