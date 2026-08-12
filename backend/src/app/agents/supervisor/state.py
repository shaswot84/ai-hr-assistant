"""Shared state for the supervisor (routing) graph.

State semantics matter: ``messages`` holds the *prior* turns of the
conversation (hydrated by the chat layer from the durable conversation
repository before each turn), while ``current_query`` is the new user
utterance in isolation. Keeping them separate means routing and query
rewriting always see exactly one question plus its context, never a
duplicated copy of the latest message.

The graph itself is stateless between turns — durability lives in the
conversation tables, not in a LangGraph checkpointer (see
``repositories/conversation.py``).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.knowledge.contracts import Citation, KnowledgeResult


class SupervisorState(TypedDict, total=False):
    """Graph state for one chat turn routed by the supervisor."""

    # Prior turns only (never the current question) — see module docstring.
    messages: Annotated[list[BaseMessage], add_messages]
    # The new user utterance, isolated from history.
    current_query: str
    # knowledge | leave | recruitment | clarify — set by the route node.
    route: str
    # Knowledge agent outputs: retrieval evidence + the final reply.
    knowledge_result: KnowledgeResult | None
    # The assistant reply text (also the last message in ``messages``).
    answer: str
    # Structured facts for durable persistence by the chat layer.
    citations: list[Citation]
    confidence: float
    # Which sub-agent handled the turn.
    agent: str
    # Output-safety verdict for the generated answer: PASS | REDACTED |
    # BLOCKED | FLAGGED_FOR_REVIEW (see safety/contracts.py).
    safety: str
