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

import json
import uuid
from collections.abc import Callable
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
    # Cross-process execution claim, injected by the node when the session
    # store is shared across workers (Redis). When bound, begin/end
    # execution delegate to the store's atomic claim instead of the
    # per-process flag.
    _claim: Callable[[], bool] | None = field(default=None, repr=False)
    _release: Callable[[], None] | None = field(default=None, repr=False)

    def bind_claim(self, claim: Callable[[], bool], release: Callable[[], None]) -> None:
        """Bind the store-backed execution claim for this turn.

        The node calls this once per turn with the session store's claim
        (in-memory per-process set, or a Redis ``SET NX EX`` cross-process
        lock). When bound, ``begin_execution``/``end_execution`` delegate to
        it, so a confirmed write is claimed atomically across processes.
        """
        self._claim = claim
        self._release = release

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

        When a store-backed claim is bound (see ``bind_claim``) it is used —
        that is the cross-process atomic claim (Redis ``SET NX EX``); the
        per-process flag below is the fallback for direct calls without a
        store (unit tests / pre-wiring callers).

        Returns True if the caller may proceed, False if another turn is
        already executing (or already executed and this is a duplicate/
        concurrent confirmation). Synchronous and awaits nothing between
        the check and the flip, so within a single asyncio event loop this
        is a true atomic test-and-set — a second concurrent "yes" for the
        same session cannot slip through between the check and the set.

        This does not protect against multiple worker PROCESSES sharing
        one session concurrently — that requires a real lock (Redis), which
        ``RedisSessionStore`` provides once ``REDIS_URL`` is configured.
        """
        if self._claim is not None:
            return self._claim()
        if self._executing:
            return False
        self._executing = True
        return True

    def end_execution(self, *, clock: Clock) -> None:
        if self._release is not None:
            self._release()
            return
        self._executing = False
        self.updated_at = clock.now()

    def history_for_prompt(self) -> list[dict[str, str]]:
        return [turn.as_dict() for turn in self.history]

    def pending_for_prompt(self) -> dict | None:
        if self.pending_confirmation is None:
            return None
        return {"tool": self.pending_confirmation.tool, "args": self.pending_confirmation.args}


# ---- durable workflow-state serialization -----------------------------------
#
# The conversation_workflow_state row stores ONLY the resumable workflow
# facts (draft + staged action + expiry) as JSON — never the transcript,
# which already lives in conversation_message. These helpers are the single
# mapping between the dataclass shapes above and that row's JSONB columns.


def draft_to_json(draft: DraftRequest | None) -> dict | None:
    """DraftRequest -> JSON-safe dict (dates as ISO strings), or None."""
    if draft is None:
        return None
    return {
        "leave_type_name": draft.leave_type_name,
        "start_date": draft.start_date.isoformat() if draft.start_date else None,
        "end_date": draft.end_date.isoformat() if draft.end_date else None,
        "reason": draft.reason,
    }


def draft_from_json(data: dict | None) -> DraftRequest | None:
    """Rebuild a DraftRequest from the stored JSON, or None for a null payload."""
    if not data:
        return None
    return DraftRequest(
        leave_type_name=data.get("leave_type_name"),
        start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else None,
        end_date=date.fromisoformat(data["end_date"]) if data.get("end_date") else None,
        reason=data.get("reason"),
    )


def pending_to_json(pending: PendingConfirmation | None) -> dict | None:
    """PendingConfirmation -> JSON-safe dict (datetimes as ISO strings), or None."""
    if pending is None:
        return None
    return {
        "confirmation_id": str(pending.confirmation_id),
        "session_id": pending.session_id,
        "actor_subject": pending.actor_subject,
        "tool": pending.tool,
        "args": pending.args,
        "summary": pending.summary,
        "created_at": pending.created_at.isoformat(),
        "expires_at": pending.expires_at.isoformat(),
    }


def pending_from_json(data: dict | None) -> PendingConfirmation | None:
    """Rebuild a PendingConfirmation from the stored JSON, or None."""
    if not data:
        return None
    return PendingConfirmation(
        confirmation_id=uuid.UUID(data["confirmation_id"]),
        session_id=data.get("session_id", ""),
        actor_subject=data.get("actor_subject", ""),
        tool=data["tool"],
        args=data["args"],
        summary=data["summary"],
        created_at=datetime.fromisoformat(data["created_at"]),
        expires_at=datetime.fromisoformat(data["expires_at"]),
    )


def workflow_snapshot(state: LeaveAgentState) -> dict:
    """The durable slice of a LeaveAgentState, in the row's JSON shape.

    Only draft + pending confirmation (+ the pending action's expiry) — the
    session id, timestamps, and history are deliberately excluded: the row
    must never duplicate the transcript, and a restored session rebuilds its
    timestamps from the Clock.
    """
    return {
        "draft": draft_to_json(state.draft),
        "pending": pending_to_json(state.pending_confirmation),
        "expires_at": (
            state.pending_confirmation.expires_at.isoformat()
            if state.pending_confirmation is not None
            else None
        ),
    }


def apply_workflow_snapshot(state: LeaveAgentState, snapshot: dict, *, clock: Clock) -> None:
    """Rebuild the durable slice of state from a stored row's JSON.

    An expired pending action is dropped DETERMINISTICALLY here — the TTL
    decision is made against the PERSISTED ``expires_at`` at restore time,
    so a process restart can never extend a confirmation's life, and an
    already-expired action is never resurrected for the model to "confirm".
    """
    draft = draft_from_json(snapshot.get("draft"))
    pending = pending_from_json(snapshot.get("pending"))
    if pending is not None and clock.now() >= pending.expires_at:
        pending = None
    state.draft = draft
    state.pending_confirmation = pending


# ---- full-session serialization (the Redis working store) -----------------
#
# The durable workflow row stores only the resumable slice (draft + pending);
# the Redis working store replaces the in-memory per-process store, so it
# must hold the FULL session — including the conversation history a turn
# landing on a different worker must see.


def session_to_json(state: LeaveAgentState) -> dict:
    """The full working slice of a session, as JSON for the working store."""
    return {
        "session_id": state.session_id,
        "actor_subject": state.actor_subject,
        "created_at": state.created_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "history": [turn.as_dict() for turn in state.history],
        "draft": draft_to_json(state.draft),
        "pending": pending_to_json(state.pending_confirmation),
    }


def session_from_json(data: dict) -> LeaveAgentState:
    """Rebuild the full working state from :func:`session_to_json` output."""
    state = LeaveAgentState(
        session_id=data["session_id"],
        actor_subject=data.get("actor_subject", ""),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )
    state.history = [
        ConversationTurn(role=turn["role"], content=turn["content"])
        for turn in data.get("history", [])
    ]
    state.draft = draft_from_json(data.get("draft"))
    state.pending_confirmation = pending_from_json(data.get("pending"))
    return state


class SessionStore:
    """In-memory cache of LeaveAgentState, keyed by session_id.

    Cache only, never the source of truth: on a miss the caller (node.py)
    restores from the durable conversation_workflow_state row before this
    store ever creates a fresh state, and writes it back after the turn.

    Not thread-safe beyond the GIL's normal dict-op atomicity — fine for a
    single-process dev/demo deployment; a multi-worker deployment would
    need this backed by Redis instead (the ephemeral-memory role
    Database_Implementation.md already allows for), not PostgreSQL.
    """

    def __init__(self, *, ttl: timedelta = DEFAULT_SESSION_TTL, clock: Clock | None = None) -> None:
        self._sessions: dict[str, LeaveAgentState] = {}
        self._ttl = ttl
        self._clock = clock or get_clock()
        # Sessions currently executing a confirmed write (see begin_execution).
        self._executing_claims: set[str] = set()

    def get(self, session_id: str, actor: UserContext) -> LeaveAgentState | None:
        """Return the cached session state, or None on a miss.

        Returns None when the session is missing, expired, or bound to a
        different identity than the caller — a client-supplied session_id is
        not a trusted identity boundary by itself: if it collides with (or
        is reused across) a different actor, resuming that state would leak
        one employee's staged leave details into another employee's
        conversation. Any mismatch is treated the same as "no session"
        rather than an error.
        """
        existing = self._sessions.get(session_id)
        if existing is not None and existing.actor_subject == actor.subject and not self._is_expired(existing):
            return existing
        return None

    def put(self, state: LeaveAgentState) -> None:
        """Cache (or overwrite) a session state."""
        self._sessions[state.session_id] = state

    def get_or_create(self, session_id: str, actor: UserContext) -> LeaveAgentState:
        """Return the cached session's state, starting fresh on any miss.

        Kept for callers that manage their own durability; node.py uses
        ``get`` + durable restore instead.
        """
        existing = self.get(session_id, actor)
        if existing is not None:
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

    def begin_execution(self, session_id: str) -> bool:
        """Claim the right to execute a staged write for this session.

        Per-process set semantics (the GIL makes the membership check + add
        atomic). ``RedisSessionStore`` overrides this with a cross-process
        atomic claim (``SET NX EX``) so multiple worker processes cannot
        both execute the same confirmation.
        """
        if session_id in self._executing_claims:
            return False
        self._executing_claims.add(session_id)
        return True

    def end_execution(self, session_id: str) -> None:
        """Release the execution claim for this session."""
        self._executing_claims.discard(session_id)

    def delete(self, session_id: str) -> None:
        """Drop the cached session and any active execution claim."""
        self._sessions.pop(session_id, None)
        self._executing_claims.discard(session_id)


class RedisSessionStore(SessionStore):
    """Redis-backed working store for LeaveAgentState (cross-process safe).

    Same interface as :class:`SessionStore`, plus a real cross-process
    execution claim: ``begin_execution`` is ``SET key NX EX`` on a per-session
    key, so two worker processes confirming the same staged action cannot
    both execute it. The durable source of truth stays the
    ``conversation_workflow_state`` row (node.py restores from it on a miss);
    this store only holds the working slice (history + draft + pending)
    between turns, with the session TTL applied by Redis itself.

    Fail-safe by design: a Redis error on ``begin_execution`` refuses the
    claim (never risks a double write); a Redis error on ``get`` is treated
    as a cache miss (the caller restores from the durable row).

    ``client`` may be a redis client or a ``fakeredis`` instance (tests);
    otherwise ``url`` is used, with redis imported lazily so the base
    install stays lean.
    """

    _KEY_PREFIX = "leave:session:"
    _CLAIM_PREFIX = "leave:exec:"
    _CLAIM_TTL_SECONDS = 10  # a claim lives at most one turn; the TTL guards a crash

    def __init__(
        self,
        *,
        url: str | None = None,
        client=None,
        ttl: timedelta = DEFAULT_SESSION_TTL,
    ) -> None:
        super().__init__(ttl=ttl)
        if client is not None:
            self._client = client
        elif url is not None:
            from redis import Redis  # lazy: redis is optional at runtime

            self._client = Redis.from_url(url, decode_responses=True)
        else:
            raise ValueError("RedisSessionStore requires url= or client=")
        # Per-process record of the claim token WE hold per session, so
        # end_execution can never release someone else's claim.
        self._held_tokens: dict[str, str] = {}

    def _session_key(self, session_id: str) -> str:
        return f"{self._KEY_PREFIX}{session_id}"

    def _claim_key(self, session_id: str) -> str:
        return f"{self._CLAIM_PREFIX}{session_id}"

    def get(self, session_id: str, actor: UserContext) -> LeaveAgentState | None:
        """Return the cached session state, or None on a miss (a Redis blip
        is a miss too — the caller restores from the durable row)."""
        try:
            raw = self._client.get(self._session_key(session_id))
        except Exception:  # noqa: BLE001 - a cache blip is never a crash
            return None
        if raw is None:
            return None
        state = session_from_json(json.loads(raw))
        if state.actor_subject != actor.subject:
            return None
        return state

    def put(self, state: LeaveAgentState) -> None:
        """Cache (or overwrite) a session state, refreshing its TTL."""
        try:
            self._client.set(
                self._session_key(state.session_id),
                json.dumps(session_to_json(state)),
                ex=int(self._ttl.total_seconds()),
            )
        except Exception:  # noqa: BLE001 - losing the working cache is survivable
            return

    def get_or_create(self, session_id: str, actor: UserContext) -> LeaveAgentState:
        """Return the cached session's state, starting fresh on any miss."""
        existing = self.get(session_id, actor)
        if existing is not None:
            return existing
        now = self._clock.now()
        fresh = LeaveAgentState(
            session_id=session_id,
            actor_subject=actor.subject,
            created_at=now,
            updated_at=now,
        )
        self.put(fresh)
        return fresh

    def purge_expired(self) -> int:
        """Redis TTLs expire keys on their own; nothing to sweep."""
        return 0

    def begin_execution(self, session_id: str) -> bool:
        """Cross-process atomic claim: SET key NX EX with an owner token.

        Returns True only for the single worker that wins the SET; the
        losing workers (or a retried request) get False and must not
        execute. On a Redis error the claim is refused — fail SAFE, never
        risk a double write.
        """
        token = uuid.uuid4().hex
        try:
            claimed = self._client.set(
                self._claim_key(session_id), token, nx=True, ex=self._CLAIM_TTL_SECONDS
            )
        except Exception:  # noqa: BLE001 - fail safe: never double-execute
            return False
        if not claimed:
            return False
        self._held_tokens[session_id] = token
        return True

    def end_execution(self, session_id: str) -> None:
        """Release OUR execution claim for this session, if we hold it.

        Compare-and-delete by owner token (WATCH/MULTI/EXEC): after a TTL
        expiry the claim may have been re-taken by another worker — this
        must not delete their claim.
        """
        token = self._held_tokens.pop(session_id, None)
        if token is None:
            return  # we never held it (or already released) — never touch another's
        try:
            with self._client.pipeline() as pipe:
                pipe.watch(self._claim_key(session_id))
                if pipe.get(self._claim_key(session_id)) != token:
                    return
                pipe.multi()
                pipe.delete(self._claim_key(session_id))
                pipe.execute()
        except Exception:  # noqa: BLE001 - a stale claim is cleared by its TTL
            return

    def delete(self, session_id: str) -> None:
        """Drop the working slice from Redis and release any active claim."""
        try:
            self._client.delete(self._session_key(session_id), self._claim_key(session_id))
        except Exception:  # noqa: BLE001 - ignore Redis errors on best-effort cleanup
            pass
        self._held_tokens.pop(session_id, None)