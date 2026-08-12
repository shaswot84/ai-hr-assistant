"""Small shared helpers for the agent package."""

from __future__ import annotations

from langchain_core.messages import BaseMessage


def history_text(messages: list[BaseMessage], *, max_messages: int = 10) -> str:
    """Serialize the most recent turns into a compact transcript.

    Oldest first, speaker-labelled, bounded to the last ``max_messages`` so
    routing and query-rewrite prompts stay small. Used by the supervisor's
    routing prompt and the knowledge agent's query-rewrite prompt.
    """
    lines = []
    for message in messages[-max_messages:]:
        speaker = "User" if message.type == "human" else "Assistant"
        lines.append(f"{speaker}: {message.content}")
    return "\n".join(lines) or "(no prior conversation)"
