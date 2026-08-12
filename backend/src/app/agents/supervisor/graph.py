"""The supervisor (routing) graph.

Structure::

    START -> route --conditional--> knowledge | leave | recruitment | clarify
    each sub-agent -> END

The route node classifies the current message (with conversation context)
into one of four routes; a conditional edge dispatches to the matching
sub-agent node; each sub-agent appends its assistant reply to ``messages``
and records structured output (answer, citations, confidence, agent) for the
chat layer to persist.

The graph is built per request with a request-scoped ``KnowledgeService``
(the same shape as the search endpoints), so it holds no state between
turns — durability lives in the conversation tables.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter

from app.agents.knowledge_agent.agent import stream_knowledge_turn
from app.agents.leave_agent.agent import make_leave_node
from app.agents.recruitment_agent.agent import make_recruitment_node
from app.agents.supervisor.clarify import make_clarify_node
from app.agents.supervisor.route_intent import route_intent
from app.agents.supervisor.state import SupervisorState
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM

ROUTE_TO_NODE = {
    "knowledge": "knowledge",
    "leave": "leave",
    "recruitment": "recruitment",
    "clarify": "clarify",
}


def make_route_node(llm: LLM | None):
    """Classify the current message into a route (LLM + keyword fallback)."""

    async def route_node(state: SupervisorState) -> dict:
        route = await route_intent(
            llm, state["current_query"], state.get("messages", [])
        )
        return {"route": route}

    return route_node


def make_knowledge_node(llm: LLM | None, service: KnowledgeService):
    """Answer the current question from the knowledge base (rewrite + RAG).

    Streams retrieval/token events through LangGraph's ``writer`` so the chat
    endpoint can forward them as SSE while the node still returns the full
    state update for persistence.
    """

    async def knowledge_node(state: SupervisorState, writer: StreamWriter) -> dict:
        return await stream_knowledge_turn(
            service=service,
            llm=llm,
            query=state["current_query"],
            history=state.get("messages", []),
            writer=writer,
        )

    return knowledge_node


def _select_route(state: SupervisorState) -> str:
    """Conditional-edge selector: follow the route the route node chose."""
    return state.get("route", "knowledge")


def build_supervisor_graph(
    *,
    llm: LLM | None,
    knowledge_service: KnowledgeService,
) -> CompiledStateGraph:
    """Assemble the supervisor graph with the given LLM and knowledge service."""
    builder = StateGraph(SupervisorState)
    builder.add_node("route", make_route_node(llm))
    builder.add_node("knowledge", make_knowledge_node(llm, knowledge_service))
    builder.add_node("leave", make_leave_node())
    builder.add_node("recruitment", make_recruitment_node())
    builder.add_node("clarify", make_clarify_node())
    builder.add_edge(START, "route")
    builder.add_conditional_edges("route", _select_route, ROUTE_TO_NODE)
    for node in ("knowledge", "leave", "recruitment", "clarify"):
        builder.add_edge(node, END)
    return builder.compile()
