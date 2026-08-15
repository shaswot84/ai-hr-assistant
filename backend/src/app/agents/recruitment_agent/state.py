"""Recruitment Agent state: per-session conversation memory and draft state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import uuid

from app.shared.clock import Clock, get_clock

MAX_HISTORY_TURNS = 12
DEFAULT_SESSION_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class ConversationTurn:
    """One message in the recruitment conversation."""

    role: str  # "candidate" | "agent" | "manager" | "user"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class DraftApplication:
    """A draft job application in progress."""

    vacancy_id: uuid.UUID | None = None
    vacancy_title: str | None = None
    cv_object_key: str | None = None
    applied_at: datetime | None = None


@dataclass
class RecruitmentAgentState:
    """One session's recruitment conversation state."""

    session_id: str
    actor_subject: str
    created_at: datetime
    updated_at: datetime
    history: list[ConversationTurn] = field(default_factory=list)
    draft_application: DraftApplication | None = None

    def add_turn(self, role: str, content: str, clock: Clock | None = None) -> None:
        clock = clock or get_clock()
        self.history.append(ConversationTurn(role=role, content=content))
        if len(self.history) > MAX_HISTORY_TURNS:
            self.history = self.history[-MAX_HISTORY_TURNS:]
        self.updated_at = clock.now()

    def history_for_prompt(self) -> list[dict[str, str]]:
        return [t.as_dict() for t in self.history]
