"""Small shared helpers for the agent package."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

# ---- thread-history question detection --------------------------------------
#
# Shared by the supervisor (route pre-check: send history questions to the
# recap node or the leave agent) and the leave agent's deterministic
# interception. Conservative on purpose: a bare "above"/"earlier" only counts
# together with a question word, and generic deixis phrases ("what did we")
# are intrinsically thread-referring — so date/leave phrasing like "can i go
# earlier" or "what did you do on friday" is never hijacked.

_HISTORY_KEYWORDS = ("recap", "summarize", "summarise", "summary", "overview of")
_HISTORY_DEIXIS = (
    "what did we",
    "what have we",
    "what was discussed",
    "what did i apply",
    "what did i ask",
    "what did i say",
)
_HISTORY_QUESTION_WORDS = ("what", "which", "why", "tell")
_HISTORY_ANCHOR_WORDS = ("above", "earlier")


def is_history_question(message: str) -> bool:
    """Is this message asking about what was said/done EARLIER in this chat?

    "recap"/"summary" and any "chat"/"conversation" mention are taken at
    face value; "above"/"earlier" count only with a question word. Anything
    else falls through to the normal (draft/model) flows.
    """
    lowered = message.lower().strip()
    if any(keyword in lowered for keyword in _HISTORY_KEYWORDS):
        return True
    if "chat" in lowered or "conversation" in lowered:
        return True
    if any(word in lowered for word in _HISTORY_ANCHOR_WORDS):
        return any(word in lowered for word in _HISTORY_QUESTION_WORDS)
    return any(phrase in lowered for phrase in _HISTORY_DEIXIS)


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
