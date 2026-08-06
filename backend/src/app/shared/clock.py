from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime


class Clock(ABC):
    """Time abstraction. Business/capability code depends on this, never on
    `datetime.now()` or SQL `NOW()` directly (HLD principle #17).

    Only `SystemClock` is implemented for the MVP. Keeping this as an
    interface (rather than a bare `utc_now()` function) leaves room for an
    accelerated `SimulationClock` later, for demos, without touching any
    capability code.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Current instant (timezone-aware)."""

    @abstractmethod
    def today(self) -> date:
        """Current calendar day."""

    def utc_now(self) -> datetime:
        """Current UTC instant. Alias of `now()` since SystemClock is always UTC."""
        return self.now()


class SystemClock(Clock):
    """Real wall-clock time (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()


_default_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """Return the active Clock. Always `SystemClock` for the MVP (no simulation mode)."""
    return _default_clock
