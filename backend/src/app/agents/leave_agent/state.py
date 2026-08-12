"""Leave Agent conversation state -- the shape, not the storage.

`agent.handle_turn` is stateless by design (see agent.py's module
docstring): it takes `history`/`pending_confirmation` in as plain
arguments and returns updated ones, holding nothing itself. This module
defines what those plain values actually look like, plus the trimming and
(de)serialization helpers around them, so every caller builds/reads that
shape the same way instead of each inventing its own dict layout.

What this module deliberately does NOT do: persist anything to a
database. `domain/conversation.py` and `repositories/conversation.py`
exist in this repo as empty stubs -- the durable-session-store question
raised earlier (per-`session_id` conversation history surviving across
HTTP requests) is still open. When that lands, `LeaveAgentSessionState`
is the shape a `ConversationRepo` should be loading into and saving out
of; nothing here needs to change, only where the dict comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.agents.leave_agent.tools import TOOLS

#: Bounded so the single-shot prompt (prompts.build_turn_prompt) never grows
#: unbounded -- this is a plain completion call, not a native multi-turn
#: chat API with its own context management. Keeps only the most recent
#: turns; older context is simply dropped, not summarized (no summarization
#: step exists yet -- see the "open questions" note at the bottom).
MAX_HISTORY_TURNS = 12

Role = Literal["employee", "agent"]


class HistoryTurn(TypedDict):
    """One prior turn, in the exact shape `prompts.build_turn_prompt` expects."""

    role: Role
    content: str


class PendingConfirmation(TypedDict):
    """A staged write action awaiting the employee's yes/no -- the exact
    shape `agent.handle_turn` reads from and writes back to on every turn."""

    tool: str
    args: dict[str, Any]


@dataclass
class LeaveAgentSessionState:
    """In-memory conversation state for one employee's Leave Agent session.

    Plain dataclass, not a Pydantic model: this never crosses the HTTP
    boundary as-is (that's `schemas/chat.py`'s job, once it exists) and
    never touches SQLAlchemy directly (that's `domain/conversation.py`'s
    job, once it exists) -- it's purely the shape passed between a route
    handler and `agent.handle_turn`.
    """

    history: list[HistoryTurn] = field(default_factory=list)
    pending_confirmation: PendingConfirmation | None = None

    def append(self, role: Role, content: str) -> None:
        """Add one turn and trim to `MAX_HISTORY_TURNS`, oldest first."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > MAX_HISTORY_TURNS:
            self.history = self.history[-MAX_HISTORY_TURNS:]

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for handing to a session store / DB row."""
        return {
            "history": list(self.history),
            "pending_confirmation": dict(self.pending_confirmation) if self.pending_confirmation else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LeaveAgentSessionState:
        """Rebuild from a stored dict, defensively -- never trust storage blindly.

        A session row could be stale (the employee's browser held an old
        `session_id` across a deploy that changed `TOOLS`), so this
        validates rather than trusting the shape outright: unknown roles
        are dropped, and a `pending_confirmation` naming a tool that no
        longer exists is discarded rather than handed to `handle_turn`,
        which would otherwise stage a confirmation for a tool call it can
        never actually run.
        """
        if not data:
            return cls()

        raw_history = data.get("history")
        history: list[HistoryTurn] = []
        if isinstance(raw_history, list):
            for turn in raw_history:
                if (
                    isinstance(turn, dict)
                    and turn.get("role") in ("employee", "agent")
                    and isinstance(turn.get("content"), str)
                ):
                    history.append({"role": turn["role"], "content": turn["content"]})
        history = history[-MAX_HISTORY_TURNS:]

        pending = data.get("pending_confirmation")
        pending_confirmation: PendingConfirmation | None = None
        if (
            isinstance(pending, dict)
            and pending.get("tool") in TOOLS
            and TOOLS[pending["tool"]].requires_confirmation
            and isinstance(pending.get("args"), dict)
        ):
            pending_confirmation = {"tool": pending["tool"], "args": dict(pending["args"])}

        return cls(history=history, pending_confirmation=pending_confirmation)


def new_session() -> LeaveAgentSessionState:
    """Fresh, empty session state for a new conversation."""
    return LeaveAgentSessionState()


# ---------------------------------------------------------------------------
# Open questions for whoever wires this to a durable store
# (domain/conversation.py + repositories/conversation.py, both empty today):
#
# 1. Key by `session_id` (per A0-A6's Database_Implementation.md-derived
#    `conversation`/`conversation_message` tables) or a simpler per-employee
#    single active session? The Leave Agent doesn't need multi-session
#    history the way a general chat UI might.
# 2. `MAX_HISTORY_TURNS` truncation currently just drops the oldest turns.
#    A real conversation table wouldn't need this at read time (it can page),
#    but the *prompt* still needs a bound -- decide whether truncation
#    happens here (recent turns only) or via a summarization step before
#    those older turns are dropped from the prompt.
# 3. `pending_confirmation` surviving a server restart matters more than
#    `history` does (an un-actioned staged write is a real liability if
#    lost silently) -- if only one of the two gets durable storage first,
#    it should be this one.
# ---------------------------------------------------------------------------