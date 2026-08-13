"""Leave Agent state: per-session conversation memory.

This is deliberately in-memory and non-durable — `Database_Implementation.md`
draws a hard line between "working/session memory" (allowed to be
ephemeral: Redis or in-memory) and "durable conversation history"
(PostgreSQL `conversation`/`conversation_message`, which don't exist yet
in this codebase). Wiring this into that durable store is route/DB-layer
work, explicitly out of scope right now (leave-agent-only, no
supervisor/persistence layer being built yet) — flagged here rather than
silently assumed away. The one thing that must never depend only on this
in-memory state is the actual business mutation — a submitted/cancelled
leave request — and it doesn't: every write still goes through
LeaveService straight to PostgreSQL.

Uses the same Clock abstraction as the rest of the codebase
(app.shared.clock) rather than datetime.now() directly, so TTL/expiry
logic is swappable/testable the same way business-logic time decisions
already are.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.contracts.auth import UserContext
from app.shared.clock import Clock, get_clock

# Trimmed to the last N turns so the prompt sent to the LLM each turn stays
# bounded — a long-running session doesn't grow the prompt without limit.
MAX_HISTORY_TURNS = 12

# Whole-session TTL: session state older than this is treated as gone.
DEFAULT_SESSION_TTL = timedelta(minutes=30)

# A staged WRITE action gets its own, much shorter TTL than the session
# itself — a "yes" arriving 25 minutes after a write was proposed
# shouldn't execute it just because the session is technically still
# alive. Re-proposing is cheap; executing a stale, half-forgotten action
# is not.
DEFAULT_CONFIRMATION_TTL = timedelta(minutes=5)


@dataclass(frozen=True)
class ConversationTurn:
    """One message in the session, in the shape prompts.build_turn_prompt expects."""

    role: str  # "employee" | "agent"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class PendingConfirmation:
    """A write action the agent has staged and is waiting on the employee to confirm.

    Carries its own identity/binding/expiry fields, not just tool+args —
    even though this object currently only ever lives inside one
    session's in-memory state (already scoped to one actor by
    SessionStore), shaping it this way now means a future durable-storage
    migration (a `pending_confirmation` table, if that's ever built) is a
    straight column mapping instead of a redesign.
    """

    confirmation_id: uuid.UUID
    session_id: str
    actor_subject: str
    tool: str
    args: dict  # canonical (JSON-safe) form — see tools.canonical_args
    summary: str
    created_at: datetime
    expires_at: datetime


@dataclass
class DraftRequest:
    """A leave-request in progress, accumulated DETERMINISTICALLY across turns.

    Dates like "tomorrow" are resolved by the dates module, never by the
    model, and the partial result is held here (not in the model's memory
    of the conversation) so a follow-up message can complete it without
    the model re-deriving anything. The draft is authoritative over a
    model-staged ``submit_leave_request``: when complete, the agent stages
    the confirmation from these exact values.
    """

    leave_type_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    reason: str | None = None

    def is_complete(self) -> bool:
        return (
            self.leave_type_name is not None
            and self.start_date is not None
            and self.end_date is not None
        )


@dataclass
class LeaveAgentState:
    """One session's conversation state."""

    session_id: str
    actor_subject: str
    created_at: datetime
    updated_at: datetime
    history: list[ConversationTurn] = field(default_factory=list)
    pending_confirmation: PendingConfirmation | None = None
    draft: DraftRequest | None = None
    _executing: bool = field(default=False, repr=False)

    def add_turn(self, role: str, content: str, *, clock: Clock) -> None:
        """Append a turn and trim history to MAX_HISTORY_TURNS (drop oldest first)."""
        self.history.append(ConversationTurn(role=role, content=content))
        if len(self.history) > MAX_HISTORY_TURNS:
            self.history = self.history[-MAX_HISTORY_TURNS:]
        self.updated_at = clock.now()

    def stage(
        self,
        tool: str,
        args: dict,
        summary: str,
        *,
        clock: Clock,
        ttl: timedelta = DEFAULT_CONFIRMATION_TTL,
    ) -> PendingConfirmation:
        """Stage a write action awaiting employee confirmation.

        Replaces any previously staged action outright — a new "stage"
        always supersedes an old one rather than merging with it, so a
        changed-subject conversation can never accidentally confirm the
        earlier, now-irrelevant action.
        """
        now = clock.now()
        pending = PendingConfirmation(
            confirmation_id=uuid.uuid4(),
            session_id=self.session_id,
            actor_subject=self.actor_subject,
            tool=tool,
            args=args,
            summary=summary,
            created_at=now,
            expires_at=now + ttl,
        )
        self.pending_confirmation = pending
        self.updated_at = now
        return pending

    def clear_pending(self, *, clock: Clock) -> None:
        """Drop any staged action — used both after executing it and after the
        employee declines/changes the subject."""
        self.pending_confirmation = None
        self.updated_at = clock.now()

    def set_draft(self, draft: DraftRequest, *, clock: Clock) -> None:
        """Replace the in-progress request draft (new info supersedes old)."""
        self.draft = draft
        self.updated_at = clock.now()

    def clear_draft(self, *, clock: Clock) -> None:
        """Drop the draft — after it is staged, cancelled, or superseded."""
        if self.draft is not None:
            self.draft = None
            self.updated_at = clock.now()

    def draft_for_prompt(self) -> dict | None:
        """The draft in a JSON-safe shape for the turn prompt, or None."""
        if self.draft is None:
            return None
        return {
            "leave_type_name": self.draft.leave_type_name,
            "start_date": self.draft.start_date.isoformat() if self.draft.start_date else None,
            "end_date": self.draft.end_date.isoformat() if self.draft.end_date else None,
        }

    def pending_is_expired(self, *, clock: Clock) -> bool:
        if self.pending_confirmation is None:
            return False
        return clock.now() >= self.pending_confirmation.expires_at

    def begin_execution(self) -> bool:
        """Atomically claim the right to execute the currently staged action.

        Returns True if the caller may proceed, False if another turn is
        already executing (or already executed and this is a duplicate/
        concurrent confirmation). Synchronous and awaits nothing between
        the check and the flip, so within a single asyncio event loop this
        is a true atomic test-and-set — a second concurrent "yes" for the
        same session cannot slip through between the check and the set.

        This does not protect against multiple worker PROCESSES sharing
        one session concurrently (this store is in-memory per-process,
        per the module docstring) — that requires a real lock (e.g. Redis)
        once this moves off a single process, which is out of scope here.
        """
        if self._executing:
            return False
        self._executing = True
        return True

    def end_execution(self, *, clock: Clock) -> None:
        self._executing = False
        self.updated_at = clock.now()

    def history_for_prompt(self) -> list[dict[str, str]]:
        return [turn.as_dict() for turn in self.history]

    def pending_for_prompt(self) -> dict | None:
        if self.pending_confirmation is None:
            return None
        return {"tool": self.pending_confirmation.tool, "args": self.pending_confirmation.args}


class SessionStore:
    """In-memory store of LeaveAgentState, keyed by session_id.

    Not thread-safe beyond the GIL's normal dict-op atomicity — fine for a
    single-process dev/demo deployment; a multi-worker deployment would
    need this backed by Redis instead (the ephemeral-memory role
    Database_Implementation.md already allows for), not PostgreSQL.
    """

    def __init__(self, *, ttl: timedelta = DEFAULT_SESSION_TTL, clock: Clock | None = None) -> None:
        self._sessions: dict[str, LeaveAgentState] = {}
        self._ttl = ttl
        self._clock = clock or get_clock()

    def get_or_create(self, session_id: str, actor: UserContext) -> LeaveAgentState:
        """Return the session's state, starting fresh if it's missing, expired,
        or bound to a different identity than the caller.

        A client-supplied session_id is not a trusted identity boundary by
        itself: if it collides with (or is reused across) a different
        actor, resuming that state would leak one employee's staged leave
        details into another employee's conversation. Any mismatch is
        treated the same as "no session" rather than an error.
        """
        existing = self._sessions.get(session_id)
        if existing is not None and existing.actor_subject == actor.subject and not self._is_expired(existing):
            return existing

        now = self._clock.now()
        fresh = LeaveAgentState(
            session_id=session_id,
            actor_subject=actor.subject,
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = fresh
        return fresh

    def _is_expired(self, state: LeaveAgentState) -> bool:
        return self._clock.now() - state.updated_at > self._ttl

    def purge_expired(self) -> int:
        """Drop expired sessions; returns how many were removed."""
        expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)