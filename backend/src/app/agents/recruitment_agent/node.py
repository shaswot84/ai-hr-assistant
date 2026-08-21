"""Recruitment node for the supervisor graph.

Integrates with ``agent.py``'s handle_turn for viewing open vacancies,
applying with resume upload, checking application status, and manager reviews.
Streams text and UI widgets through LangGraph's StreamWriter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.agents.recruitment_agent.agent import handle_turn
from app.capabilities.recruitment import RecruitmentService
from app.contracts.auth import UserContext
from app.db.session import async_session_factory
from app.model_gateway.provider import ChatProvider

if TYPE_CHECKING:
    from app.agents.supervisor.state import SupervisorState


def make_recruitment_node(
    *,
    actor: UserContext | None = None,
    service: RecruitmentService | None = None,
    chat_provider: ChatProvider | None = None,
) -> Callable[[SupervisorState, StreamWriter], Awaitable[dict]]:
    """Build the recruitment node for the supervisor graph."""

    async def recruitment_node(state: SupervisorState, writer: StreamWriter) -> dict:
        query = state.get("current_query", "")
        if service is not None:
            result = await handle_turn(
                actor=actor,
                state=None,
                service=service,
                chat_provider=chat_provider,
                user_message=query,
            )
        else:
            async with async_session_factory() as db:
                result = await handle_turn(
                    actor=actor,
                    state=None,
                    service=RecruitmentService(db),
                    chat_provider=chat_provider,
                    user_message=query,
                )

        writer({"type": "message", "text": result.reply})
        if result.ui_widget:
            writer({"type": "ui_widget", "widget": result.ui_widget})

        return {
            "messages": [AIMessage(content=result.reply)],
            "knowledge_result": None,
            "answer": result.reply,
            "citations": [],
            "confidence": 0.0,
            "agent": "recruitment",
            "safety": "PASS",
            "ui_widget": result.ui_widget,
        }

    return recruitment_node

