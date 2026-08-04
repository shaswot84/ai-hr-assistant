from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Injected clock reading for business logic — never SQL NOW().

    Returns a timezone-aware UTC timestamp.
    """
    return datetime.now(UTC)