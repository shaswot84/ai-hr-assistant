"""Leave Agent: deterministic relative-date resolution unit tests.

`today` is fixed so every assertion is independent of the wall clock.
2026-08-13 is a Thursday.
"""

from __future__ import annotations

from datetime import date

from app.agents.leave_agent.dates import (
    extract_dates,
    format_short,
    resolve_end_date,
    resolve_start_date,
)

TODAY = date(2026, 8, 13)  # Thursday


def test_resolve_start_tomorrow():
    assert resolve_start_date("tomorrow", TODAY) == date(2026, 8, 14)


def test_resolve_start_day_after_tomorrow():
    assert resolve_start_date("the day after tomorrow", TODAY) == date(2026, 8, 15)


def test_resolve_start_today():
    assert resolve_start_date("today", TODAY) == TODAY


def test_resolve_start_in_n_days():
    assert resolve_start_date("in 3 days", TODAY) == date(2026, 8, 16)


def test_resolve_start_next_monday_from_thursday():
    # This coming monday (Aug 17) is already next week.
    assert resolve_start_date("next monday", TODAY) == date(2026, 8, 17)


def test_resolve_start_next_friday_from_thursday():
    # Plain friday is tomorrow (still this week) — "next friday" means a week later.
    assert resolve_start_date("friday", TODAY) == date(2026, 8, 14)
    assert resolve_start_date("next friday", TODAY) == date(2026, 8, 21)


def test_resolve_start_explicit_dates():
    assert resolve_start_date("2026-09-01", TODAY) == date(2026, 9, 1)
    assert resolve_start_date("09/02/2026", TODAY) == date(2026, 9, 2)


def test_resolve_start_fails_closed():
    assert resolve_start_date("whenever works", TODAY) is None
    assert resolve_start_date("", TODAY) is None


def test_resolve_end_for_n_days():
    assert resolve_end_date("for 3 days", date(2026, 8, 14), TODAY) == date(2026, 8, 16)


def test_resolve_end_weekday_anchored_on_start():
    # "from next monday to friday": the friday after that monday, not the
    # friday relative to today.
    start = date(2026, 8, 17)
    assert resolve_end_date("friday", start, TODAY) == date(2026, 8, 21)


def test_resolve_end_explicit():
    assert resolve_end_date("2026-09-05", date(2026, 9, 1), TODAY) == date(2026, 9, 5)


def test_resolve_end_before_start_fails_closed():
    assert resolve_end_date("tomorrow", date(2026, 8, 20), TODAY) is None
    assert resolve_end_date("2026-08-01", date(2026, 8, 20), TODAY) is None


def test_resolve_end_fails_closed():
    assert resolve_end_date("sometime", date(2026, 8, 14), TODAY) is None


def test_extract_dates_range():
    assert extract_dates("from next monday to friday", TODAY) == (
        date(2026, 8, 17),
        date(2026, 8, 21),
    )


def test_extract_dates_explicit_range():
    assert extract_dates("from 2026-09-01 to 2026-09-05", TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 5),
    )


def test_extract_dates_tomorrow_for_days():
    assert extract_dates("tomorrow for 3 days", TODAY) == (
        date(2026, 8, 14),
        date(2026, 8, 16),
    )


def test_extract_dates_start_only():
    assert extract_dates("tomorrow", TODAY) == (date(2026, 8, 14), None)


def test_extract_dates_to_weekday():
    assert extract_dates("monday to wednesday", TODAY) == (
        date(2026, 8, 17),
        date(2026, 8, 19),
    )


def test_extract_dates_fails_closed():
    assert extract_dates("i want to apply for leave", TODAY) == (None, None)
    assert extract_dates("", TODAY) == (None, None)


def test_resolve_end_same_day():
    start = date(2026, 8, 14)
    assert resolve_end_date("same day", start, TODAY) == start
    assert resolve_end_date("1 day", start, TODAY) == start
    assert resolve_end_date("just 1 day", start, TODAY) == start
    assert resolve_end_date("tomorrow", start, TODAY) == start


def test_extract_dates_single_day():
    assert extract_dates("apply 1 day annual leave tomorrow", TODAY) == (
        date(2026, 8, 14),
        date(2026, 8, 14),
    )
    assert extract_dates("take tomorrow off", TODAY) == (
        date(2026, 8, 14),
        date(2026, 8, 14),
    )
    assert extract_dates("from 2026-09-01 to 2026-09-01", TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 1),
    )


def test_format_short():
    assert format_short(date(2026, 8, 14)) == "Fri, Aug 14, 2026"