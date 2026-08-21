"""Deterministic relative-date resolution for the Leave Agent.

The model is told (prompts rule 10/11) never to convert relative dates —
"tomorrow", "next monday", "for 3 days" — into specific dates itself. This
module is the code that actually does it, so date understanding never
depends on the live model getting it right. Same discipline as
``mentioned_leave_type`` in tools.py: fail closed (``None``) on anything
unrecognized — never guess.

Everything is a pure function of ``today`` (the ``Clock`` abstraction from
app.shared.clock, injected by the caller), so tests are deterministic.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEEKDAY_INDEX = {name: i for i, name in enumerate(_WEEKDAY_NAMES)}

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MDY_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_TOMORROW_RE = re.compile(r"\btomorrow\b")
_DAY_AFTER_RE = re.compile(r"\b(the\s+)?day after tomorrow\b")
_TODAY_RE = re.compile(r"\btoday\b")
_IN_DAYS_RE = re.compile(r"\bin\s+(\d+)\s+days?\b")
_FOR_DAYS_RE = re.compile(r"\bfor\s+(\d+)\s+days?\b")
_NEXT_WEEKDAY_RE = re.compile(r"\bnext\s+(" + "|".join(_WEEKDAY_NAMES) + r")\b")
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(_WEEKDAY_NAMES) + r")\b")
_RANGE_RE = re.compile(r"\bfrom\s+(.+?)\s+to\s+(.+)$")
_TO_RE = re.compile(r"\bto\s+(.+)$")


def _parse_explicit(text: str) -> date | None:
    """An explicit calendar date: ``YYYY-MM-DD`` or ``MM/DD/YYYY``."""
    for m in _ISO_DATE_RE.finditer(text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    for m in _MDY_DATE_RE.finditer(text):
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
    return None


def _weekday_delta(name: str, base: date, *, force_next: bool = False) -> timedelta:
    """Offset from ``base`` to the next occurrence of weekday ``name``.

    ``force_next`` (the "next <weekday>" form) means "the one in the NEXT
    week": an occurrence still in the CURRENT week (a later weekday than
    ``base``) moves a full week further out, and the same weekday as
    ``base`` means a week out — "next friday" said on a Thursday is next
    week's friday, while "next monday" said on a Thursday is this coming
    monday (already next week)."""
    target = _WEEKDAY_INDEX[name]
    days = (target - base.weekday()) % 7
    if force_next:
        if days == 0:
            days = 7
        elif base.weekday() < target:
            days += 7
    return timedelta(days=days)


def _resolve_relative_day(text: str, today: date) -> date | None:
    """A relative day from ``text``, resolved against ``today``. Fail closed."""
    if _DAY_AFTER_RE.search(text):
        return today + timedelta(days=2)
    if _TOMORROW_RE.search(text):
        return today + timedelta(days=1)
    if _TODAY_RE.search(text):
        return today
    m = _IN_DAYS_RE.search(text)
    if m is not None:
        return today + timedelta(days=int(m.group(1)))
    m = _NEXT_WEEKDAY_RE.search(text)
    if m is not None:
        return today + _weekday_delta(m.group(1), today, force_next=True)
    m = _WEEKDAY_RE.search(text)
    if m is not None:
        return today + _weekday_delta(m.group(1), today)
    return None


def resolve_start_date(text: str, today: date) -> date | None:
    """Resolve the start date mentioned in ``text``, or ``None`` if unknown.

    Order: explicit calendar date first, then relative words ("tomorrow",
    "in 3 days", "next monday", "monday"). Never guesses.
    """
    lowered = text.lower()
    explicit = _parse_explicit(lowered)
    if explicit is not None:
        return explicit
    return _resolve_relative_day(lowered, today)


def _looks_like_day_phrase(text: str) -> bool:
    """An end-of-range fragment must be a DATE phrase, not prose.

    "from monday to friday" passes ("friday"), but "want to apply for annual
    leave tomorrow" must not be treated as a range end just because it
    contains the word "to". Explicit dates and "for N days" are handled
    before this check; it guards the bare-weekday path only.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    return len(words) <= 2


_SAME_DAY_PHRASES = (
    "same day",
    "same date",
    "same",
    "1 day",
    "one day",
    "single day",
    "1-day",
    "just 1 day",
    "only 1 day",
    "just today",
    "just tomorrow",
    "that day",
    "just that day",
)


def resolve_end_date(text: str, start: date, today: date) -> date | None:
    """Resolve the end date mentioned in ``text``, given the start date.

    Supports an explicit date (>= start), "same day" / "1 day", "for N days",
    a weekday phrase anchored on ``start``, or a relative day word ("tomorrow", "today") >= start.
    """
    lowered = text.strip().lower()

    # 1. Same-day / 1-day phrases
    if any(re.search(rf"\b{re.escape(p)}\b", lowered) for p in _SAME_DAY_PHRASES):
        return start

    # 2. Explicit date
    explicit = _parse_explicit(lowered)
    if explicit is not None:
        return explicit if explicit >= start else None

    # 3. "for N days" or "N days"
    m = _FOR_DAYS_RE.search(lowered)
    if m is not None:
        days_count = int(m.group(1))
        return start + timedelta(days=max(0, days_count - 1))

    m_days = re.search(r"\b(\d+)\s+days?\b", lowered)
    if m_days is not None and _looks_like_day_phrase(lowered):
        days_count = int(m_days.group(1))
        return start + timedelta(days=max(0, days_count - 1))

    if not _looks_like_day_phrase(lowered):
        return None

    # 4. Weekdays anchored on start (e.g. "from next monday to friday")
    m = _NEXT_WEEKDAY_RE.search(lowered)
    if m is not None:
        return start + _weekday_delta(m.group(1), start, force_next=True)
    m = _WEEKDAY_RE.search(lowered)
    if m is not None:
        return start + _weekday_delta(m.group(1), start)

    # 5. Relative day ("tomorrow", "today", "day after tomorrow", "in N days")
    rel = _resolve_relative_day(lowered, today)
    if rel is not None:
        return rel if rel >= start else None

    return None


def extract_dates(text: str, today: date) -> tuple[date | None, date | None]:
    """Both dates from one message, when present: ``(start, end)``.

    Handles "from monday to friday", "tomorrow for 3 days", "next monday to
    next friday", "on 2026-08-14 for 2 days", "1 day annual leave tomorrow", ...
    Either half may be ``None`` when it cannot be resolved — never guessed.
    """
    lowered = text.lower()
    m = _RANGE_RE.search(lowered)
    if m is not None:
        start = resolve_start_date(m.group(1), today)
        if start is None:
            return None, None
        return start, resolve_end_date(m.group(2), start, today)

    # Check for single-day leave indicators in the initial request
    is_single_day = bool(
        re.search(r"\b(1\s*day|one\s*day|single\s*day|1-day|same\s*day|day\s*off)\b", lowered)
        or re.search(r"\btake\s+.+?\s+off\b", lowered)
    )

    start = resolve_start_date(lowered, today)
    if start is None:
        return None, None

    if is_single_day:
        return start, start

    fm = _FOR_DAYS_RE.search(lowered)
    if fm is not None:
        return start, start + timedelta(days=int(fm.group(1)) - 1)
    tm = _TO_RE.search(lowered)
    if tm is not None:
        return start, resolve_end_date(tm.group(1), start, today)
    return start, None


def extract_half_day_info(text: str) -> tuple[bool, str | None]:
    """Detect if the message mentions half-day leave and resolve the period ('MORNING' | 'AFTERNOON')."""
    lowered = text.lower()
    has_half = bool(
        re.search(r"\b(half\s*day|0\.5\s*days?|half-day)\b", lowered)
        or re.search(r"\b(morning|afternoon|first\s*half|second\s*half)\b", lowered)
    )
    if not has_half:
        return False, None

    if re.search(r"\b(afternoon|second\s*half|pm)\b", lowered):
        return True, "AFTERNOON"
    if re.search(r"\b(morning|first\s*half|am)\b", lowered):
        return True, "MORNING"
    return True, "MORNING"


def format_short(d: date) -> str:
    """A compact, unambiguous display form: ``Fri, Aug 14, 2026``."""
    return d.strftime("%a, %b %d, %Y")