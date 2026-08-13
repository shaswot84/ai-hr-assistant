"""Chat API: the conversation endpoint over the supervisor graph.

One turn of ``POST /api/chat``:

1. Resolve the authenticated user to ``application_user.user_id`` (the
   durable owner — candidates have no employee row, so the conversation key
   is never an employee id).
2. Create the conversation on first turn (title from the first message) and
   persist the user message *before* running the graph, so a crash mid-turn
   never loses the user's words.
3. Hydrate the supervisor graph with the prior turns from the conversation
   repository and run it with the new message as ``current_query``.
4. Persist the assistant reply (answer, citations, agent, confidence) and
   touch the conversation so it rises in the history list.

The graph is built per request with a request-scoped ``KnowledgeService`` —
the same shape as the search endpoints. ``build_chat_graph`` is the seam
tests replace with fakes.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.leave_agent.state import SessionStore
from app.agents.supervisor.graph import build_supervisor_graph
from app.api.deps import require_role
from app.contracts.auth import UserContext
from app.db.session import get_session
from app.domain.conversation import ConversationMessage
from app.domain.identity import ApplicationUser
from app.knowledge.contracts import Citation, KnowledgeResult
from app.knowledge.repository import HybridRetrievalRepository
from app.knowledge.service import KnowledgeService
from app.model_gateway.factory import build_embedder, build_llm, build_reranker
from app.model_gateway.interfaces import LLM, Embedder, Reranker
from app.model_gateway.ollama import OllamaChatProvider
from app.repositories.conversation import ConversationRepo
from app.safety.factory import build_output_guard
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    CitationOut,
    ConversationSummary,
    MessageOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Every authenticated role can chat: HR admins, employees, and candidates
# (the candidate portal's chatbot is a first-class consumer).
ALL_ROLES = ("HR_ADMIN", "EMPLOYEE", "CANDIDATE")

_TITLE_MAX = 80

# Terminal nodes in the supervisor graph — their state update is the final
# answer the chat layer persists.
_TERMINAL_NODES = ("knowledge", "leave", "recruitment", "clarify")

# Bounded history window fed to the graph per turn, measured in tokens
# (deterministic 4-characters-per-token estimate), not message count — the
# routing/rewrite prompts stay within budget no matter how long the
# individual messages are. The sub-agent prompts trim further by their own
# budgets (see agents/context.py).
_HISTORY_TOKEN_BUDGET = 5000


def _embedder() -> Embedder:
    """Model Gateway embedder singleton (Ollama by default)."""
    embedder = getattr(_embedder, "_embedder", None)
    if embedder is None:
        embedder = build_embedder()
        _embedder._embedder = embedder
    return embedder


def _reranker() -> Reranker:
    """Model Gateway reranker singleton (lazy; pass-through when disabled)."""
    reranker = getattr(_reranker, "_reranker", None)
    if reranker is None:
        reranker = build_reranker()
        _reranker._reranker = reranker
    return reranker


def _llm() -> LLM | None:
    """Generation/routing LLM singleton; None when disabled or misconfigured."""
    llm = getattr(_llm, "_llm", None)
    if llm is None:
        llm = build_llm()
        _llm._llm = llm
    return llm


def _leave_store() -> SessionStore:
    """Process-wide leave session store (keyed by conversation id).

    The leave agent keeps staged confirmations between turns; the session
    store must outlive a single request, so it's a module singleton like the
    embedder/LLM above. See leave_agent/state.py for TTL/identity rules.
    """
    store = getattr(_leave_store, "_store", None)
    if store is None:
        store = SessionStore()
        _leave_store._store = store
    return store


def build_chat_graph(session: AsyncSession, user: UserContext):
    """Assemble the supervisor graph for this request.

    Request-scoped like the search endpoints: the KnowledgeService binds the
    repository to this request's session, and the graph holds no state
    between turns (durability lives in the conversation tables). The
    output-safety pipeline (claim tracking, evidence gate, PII, topics) is
    wired from settings and applied to every generated answer.

    The leave agent is wired with the authenticated actor and the shared
    session store so it can run real balance/request tools.
    """
    service = KnowledgeService(
        HybridRetrievalRepository(session),
        _embedder(),
        reranker=_reranker(),
        llm=_llm(),
    )
    return build_supervisor_graph(
        llm=_llm(),
        knowledge_service=service,
        guard=build_output_guard(),
        leave_actor=user,
        leave_store=_leave_store(),
        leave_chat_provider=OllamaChatProvider(),
    )


async def _resolve_user_id(session: AsyncSession, user: UserContext) -> uuid.UUID:
    """Map the JWT subject to its application_user.user_id.

    Mirrors ``IdentityService._get_app_user`` but against the async session
    the chat pipeline already holds — chat is the one flow that crosses from
    the async (knowledge) side of the app into identity.
    """
    stmt = select(ApplicationUser.user_id).where(
        ApplicationUser.identity_provider == "local",
        ApplicationUser.external_subject == user.subject,
    )
    user_id = await session.scalar(stmt)
    if user_id is None:
        raise HTTPException(status_code=401, detail="authenticated user has no application_user record")
    return user_id


def _history_messages(rows: list[ConversationMessage]) -> list[BaseMessage]:
    """Convert stored transcript rows into LangChain messages for graph state."""
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content))
    return messages


def _make_title(message: str) -> str:
    """Derive a readable history-list title from the first message."""
    return message if len(message) <= _TITLE_MAX else f"{message[:_TITLE_MAX]}…"


def _serialize_citation(citation: Citation) -> dict:
    """Citation -> JSON shape for the JSONB column and the API response."""
    return {
        "chunk_id": str(citation.chunk_id),
        "document_id": str(citation.document_id),
        "document_version_id": str(citation.document_version_id),
        "version_number": citation.version_number,
        "document_title": citation.document_title,
        "category": citation.category,
        "page": citation.page,
        "section_title": citation.section_title,
    }


def _serialize_retrieval_event(event: dict) -> dict:
    """The knowledge node's retrieval event -> JSON for SSE."""
    result: KnowledgeResult = event["result"]
    return {
        "type": "retrieval",
        "rewritten_query": event["rewritten_query"],
        "grounded_context": result.grounded_context,
        "confidence": round(result.confidence, 4),
        "low_confidence": result.low_confidence,
        "citations": [_serialize_citation(c) for c in result.citations],
    }


async def _prepare_turn(
    session: AsyncSession, user: UserContext, body: ChatRequest
) -> tuple[ConversationRepo, uuid.UUID, list[BaseMessage], str]:
    """Validate, create/get the conversation, persist the user message, hydrate history.

    Runs before any streaming starts so validation errors surface as proper
    HTTP errors, and so the user's words are durable even if the graph fails
    mid-stream.
    """
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    user_id = await _resolve_user_id(session, user)
    repo = ConversationRepo(session)

    if body.conversation_id is None:
        conversation = await repo.create(user_id=user_id, title=_make_title(message))
        conversation_id = conversation.conversation_id
    else:
        conversation_id = body.conversation_id
        conversation = await repo.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        if conversation.title is None:
            await repo.set_title(conversation_id, _make_title(message))

    # Persist the user turn before the graph runs: durable even on crash.
    await repo.append_message(conversation_id=conversation_id, role="user", content=message)

    # History = the bounded window before this turn (current_query is separate).
    transcript = await repo.recent_messages_within_tokens(conversation_id, _HISTORY_TOKEN_BUDGET)
    history_messages = _history_messages(transcript[:-1])
    return repo, conversation_id, history_messages, message


async def _persist_reply(
    repo: ConversationRepo,
    conversation_id: uuid.UUID,
    answer: str,
    citations: list[dict],
    agent: str,
    confidence: float,
    low_confidence: bool = False,
    safety: str = "PASS",
) -> None:
    """Append the assistant reply and bump the conversation's activity time."""
    await repo.append_message(
        conversation_id=conversation_id,
        role="assistant",
        content=answer,
        citations=citations,
        meta={
            "agent": agent,
            "confidence": confidence,
            "low_confidence": low_confidence,
            "safety": safety,
        },
    )
    await repo.touch(conversation_id)


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: UserContext = Depends(require_role(*ALL_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """Run one chat turn through the supervisor graph and persist it."""
    repo, conversation_id, history_messages, message = await _prepare_turn(session, user, body)

    graph = build_chat_graph(session, user)
    result = await graph.ainvoke(
        {
            "messages": history_messages,
            "current_query": message,
            "conversation_id": str(conversation_id),
        }
    )

    answer = result.get("answer", "")
    citations = [_serialize_citation(c) for c in result.get("citations", [])]
    agent = result.get("agent", "unknown")
    confidence = result.get("confidence", 0.0)
    knowledge_result = result.get("knowledge_result")
    safety = result.get("safety", "PASS")

    await _persist_reply(
        repo,
        conversation_id,
        answer,
        citations,
        agent,
        confidence,
        low_confidence=bool(knowledge_result is not None and knowledge_result.low_confidence),
        safety=safety,
    )
    await session.commit()

    return ChatResponse(
        conversation_id=conversation_id,
        message=answer,
        citations=[CitationOut(**c) for c in citations],
        confidence=confidence,
        low_confidence=bool(knowledge_result is not None and knowledge_result.low_confidence),
        agent=agent,
    )


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: UserContext = Depends(require_role(*ALL_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE variant of ``POST /api/chat``: streams retrieval + answer tokens.

    Wire format is one SSE event per line (JSON in ``data:``)::

        data: {"type": "turn_started", "conversation_id": "..."}

        data: {"type": "route", "route": "knowledge"}

        data: {"type": "retrieval", "rewritten_query": "...", "grounded_context": "...",
               "confidence": 0.92, "low_confidence": false, "citations": [...]}

        data: {"type": "token", "text": "..."}

        data: {"type": "done", "conversation_id": "...", "message": "...",
               "citations": [...], "confidence": ..., "low_confidence": ..., "agent": "knowledge"}

    Stub agents (leave/recruitment) and the no-LLM grounded-context fallback
    emit a single ``message`` event instead of tokens. Validation and the
    user-message persistence happen before streaming starts; the assistant
    reply is persisted when the stream completes. On failure an ``error``
    event is emitted before ``done``.
    """
    repo, conversation_id, history_messages, message = await _prepare_turn(session, user, body)
    graph = build_chat_graph(session, user)

    def sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    async def event_stream():
        yield sse({"type": "turn_started", "conversation_id": str(conversation_id)})
        final: dict = {}
        try:
            async for mode, chunk in graph.astream(
                {
                    "messages": history_messages,
                    "current_query": message,
                    "conversation_id": str(conversation_id),
                },
                stream_mode=["custom", "updates"],
            ):
                if mode == "custom":
                    if chunk["type"] == "retrieval":
                        yield sse(_serialize_retrieval_event(chunk))
                    else:
                        yield sse(chunk)  # token / message
                else:  # updates: route first, then the terminal agent
                    for node_name, update in chunk.items():
                        if node_name == "route":
                            yield sse({"type": "route", "route": update.get("route", "knowledge")})
                        elif node_name in _TERMINAL_NODES:
                            final = update
        except Exception as exc:  # noqa: BLE001 - the stream must terminate cleanly
            logger.warning("chat stream failed for conversation %s: %s", conversation_id, exc)
            yield sse({"type": "error", "detail": "The assistant failed to respond. Please try again."})
            yield sse(
                {
                    "type": "done",
                    "conversation_id": str(conversation_id),
                    "message": "",
                    "citations": [],
                    "confidence": 0.0,
                    "low_confidence": False,
                    "agent": "unknown",
                }
            )
            return

        answer = final.get("answer", "")
        citations = [_serialize_citation(c) for c in final.get("citations", [])]
        agent = final.get("agent", "unknown")
        confidence = final.get("confidence", 0.0)
        knowledge_result = final.get("knowledge_result")
        safety = final.get("safety", "PASS")

        await _persist_reply(
            repo,
            conversation_id,
            answer,
            citations,
            agent,
            confidence,
            low_confidence=bool(
                knowledge_result is not None and knowledge_result.low_confidence
            ),
            safety=safety,
        )
        await session.commit()

        yield sse(
            {
                "type": "done",
                "conversation_id": str(conversation_id),
                "message": answer,
                "citations": citations,
                "confidence": confidence,
                "low_confidence": bool(
                    knowledge_result is not None and knowledge_result.low_confidence
                ),
                "agent": agent,
            }
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    user: UserContext = Depends(require_role(*ALL_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationSummary]:
    """The authenticated user's conversations, most recently active first."""
    user_id = await _resolve_user_id(session, user)
    conversations = await ConversationRepo(session).list_for_user(user_id)
    return [
        ConversationSummary(
            conversation_id=c.conversation_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    user: UserContext = Depends(require_role(*ALL_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    """A conversation's transcript, oldest first; 404 unless it is the user's."""
    user_id = await _resolve_user_id(session, user)
    repo = ConversationRepo(session)
    conversation = await repo.get(conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = await repo.list_messages(conversation_id)
    return [
        MessageOut(
            message_id=m.message_id,
            role=m.role,
            content=m.content,
            citations=m.citations,
            meta=m.meta,
            created_at=m.created_at,
        )
        for m in messages
    ]
