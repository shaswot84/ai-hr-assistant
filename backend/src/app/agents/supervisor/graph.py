"""The supervisor (routing) graph.

Structure::

    START -> route --conditional--> knowledge | leave | recruitment | clarify | recap
    each sub-agent -> END

The route node classifies the current message (with conversation context)
into one of four routes; a conditional edge dispatches to the matching
sub-agent node; each sub-agent appends its assistant reply to ``messages``
and records structured output (answer, citations, confidence, agent) for the
chat layer to persist. Thread-history questions ("what is this chat about?")
are pre-routed deterministically — to the recap node for generic recaps,
to the leave agent for leave-scoped ones.

The graph is built per request with a request-scoped ``KnowledgeService``
(the same shape as the search endpoints), so it holds no state between
turns — durability lives in the conversation tables.

- The knowledge node runs the RAG pipeline (rewrite + retrieve + generate +
  output safety) for the current query.
- The leave node is the real Leave Agent dispatch loop when the chat layer
  wires its deps (actor, session store, chat provider); otherwise an honest
  stub until that wiring lands (tests / pre-wiring callers).
- Recruitment and clarify remain placeholders.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from app.agents.knowledge_agent.agent import stream_knowledge_turn
from app.agents.leave_agent.node import make_leave_node
from app.agents.leave_agent.state import SessionStore
from app.agents.recruitment_agent.agent import make_recruitment_node
from app.agents.supervisor.clarify import make_clarify_node
from app.agents.supervisor.recap import make_recap_node, route_history_question
from app.agents.supervisor.route_intent import route_intent
from app.agents.supervisor.state import SupervisorState
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM
from app.model_gateway.provider import ChatProvider
from app.safety.interfaces import ResponseGuard

ROUTE_TO_NODE = {
    "knowledge": "knowledge",
    "leave": "leave",
    "recruitment": "recruitment",
    "clarify": "clarify",
    "recap": "recap",
}

_LEAVE_STUB = (
    "Leave isn't available in chat yet. Please use the **Leave** section in "
    "the portal to request leave or check your balance."
)


def make_route_node(llm: LLM | None):
    """Classify the current message into a route (LLM + keyword fallback).

    Thread-history questions are pre-routed deterministically, before the
    LLM is ever consulted: the LLM (and the keyword fallback) have no
    notion of "this conversation", so without the pre-check those messages
    land in clarify and the thread recap is lost.
    """

    async def route_node(state: SupervisorState) -> dict:
        deterministic = route_history_question(state["current_query"])
        if deterministic is not None:
            return {"route": deterministic}
        route = await route_intent(
            llm, state["current_query"], state.get("messages", [])
        )
        return {"route": route}

    return route_node


def make_knowledge_node(llm: LLM | None, service: KnowledgeService, guard: ResponseGuard | None = None):
    """Answer the current question from the knowledge base (rewrite + RAG).

    Streams retrieval/token events through LangGraph's ``writer`` so the chat
    endpoint can forward them as SSE while the node still returns the full
    state update for persistence. ``guard`` is the output-safety pipeline
    applied to the completed answer (claim tracking + evidence gating).
    """

    async def knowledge_node(state: SupervisorState, writer: StreamWriter) -> dict:
        return await stream_knowledge_turn(
            service=service,
            llm=llm,
            query=state["current_query"],
            history=state.get("messages", []),
            writer=writer,
            guard=guard,
        )

    return knowledge_node


def _select_route(state: SupervisorState) -> str:
    """Conditional-edge selector: follow the route the route node chose."""
    return state.get("route", "knowledge")


def _leave_stub_node() -> Callable[[SupervisorState, StreamWriter], dict]:
    """Honest placeholder: leave exists as a capability, but the agent isn't
    wired into this graph build (tests / pre-wiring callers)."""

    async def leave_node(state: SupervisorState, writer: StreamWriter) -> dict:
        writer({"type": "message", "text": _LEAVE_STUB})
        return {
            "messages": [AIMessage(content=_LEAVE_STUB)],
            "knowledge_result": None,
            "answer": _LEAVE_STUB,
            "citations": [],
            "confidence": 0.0,
            "agent": "leave",
        }

    return leave_node


def build_supervisor_graph(
    *,
    llm: LLM | None,
    knowledge_service: KnowledgeService,
    guard: ResponseGuard | None = None,
    leave_actor: UserContext | None = None,
    leave_store: SessionStore | None = None,
    leave_chat_provider: ChatProvider | None = None,
    leave_service: LeaveService | None = None,
) -> CompiledStateGraph:
    """Assemble the supervisor graph with the given LLM, knowledge service,
    and safety guard.

    The leave agent is the real dispatch loop when the chat layer wires
    ``leave_actor``/``leave_store``/``leave_chat_provider`` (all three);
    otherwise the leave node is an honest stub. ``leave_service`` is an
    optional test injection point.
    """
    builder = StateGraph(SupervisorState)
    builder.add_node("route", make_route_node(llm))
    builder.add_node("knowledge", make_knowledge_node(llm, knowledge_service, guard))
    if leave_actor is not None and leave_store is not None and leave_chat_provider is not None:
        builder.add_node(
            "leave",
            make_leave_node(
                actor=leave_actor,
                store=leave_store,
                chat_provider=leave_chat_provider,
                leave_service=leave_service,
            ),
        )
    else:
        builder.add_node("leave", _leave_stub_node())
    builder.add_node("recruitment", make_recruitment_node())
    builder.add_node("clarify", make_clarify_node())
    builder.add_node("recap", make_recap_node(llm))
    builder.add_edge(START, "route")
    builder.add_conditional_edges("route", _select_route, ROUTE_TO_NODE)
    for node in ("knowledge", "leave", "recruitment", "clarify", "recap"):
        builder.add_edge(node, END)
    return builder.compile()