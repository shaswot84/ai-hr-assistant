"""Small shared helpers for the agent package."""

from __future__ import annotations

from langchain_core.messages import BaseMessage


def history_text(
    messages: list[BaseMessage],
    *,
    max_tokens: int = 2000,
    max_messages: int = 60,
) -> str:
    """Serialize the most recent turns into a compact transcript.

    Oldest first, speaker-labelled, bounded by BOTH a message count and an
    estimated token budget (``chars / 4``) so prompts stay small no matter
    how long generated answers grow. When the budget is exceeded the OLDEST
    turns are dropped — the latest context is always kept. Used by the
    supervisor's routing prompt and the knowledge agent's query-rewrite and
    generation prompts.
    """
    selected = messages[-max_messages:]
    budgeted: list[str] = []
    tokens = 0
    for message in reversed(selected):
        speaker = "User" if message.type == "human" else "Assistant"
        line = f"{speaker}: {message.content}"
        cost = len(line) // 4 + 1
        # Always keep the newest message, even if it alone exceeds the budget.
        if budgeted and tokens + cost > max_tokens:
            break
        budgeted.append(line)
        tokens += cost
    budgeted.reverse()
    return "\n".join(budgeted) or "(no prior conversation)"
