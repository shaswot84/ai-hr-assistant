"""Route tests for the chat API.

The chat router is exercised against a purpose-built FastAPI app with the
auth and session dependencies overridden (a fixed UserContext + async SQLite)
and the graph builder swapped for one using a fake LLM and fake knowledge
service — the same seam the real wiring uses at the model-service boundary.
Nothing here touches Ollama, MinIO, or pgvector.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routes import chat as chat_module
from app.contracts.auth import UserContext
from app.db.base import Base
from app.db.session import get_session
from app.domain.conversation import Conversation, ConversationMessage, ConversationWorkflowState
from app.domain.identity import ApplicationUser, Person
from app.knowledge.contracts import Citation, KnowledgeResult
from app.model_gateway.interfaces import LLM
from app.repositories.conversation import ConversationRepo
from app.shared.clock import get_clock

# --- fakes -----------------------------------------------------------------


class FakeLLM(LLM):
    """An LLM stub with a canned completion; records prompts for assertions."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


class FakeKnowledgeService:
    """A KnowledgeService stub returning a fixed retrieval result."""

    def __init__(self, result: KnowledgeResult, answer: str | None) -> None:
        self.result = result
        self.answer = answer

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        return self.result

    async def generate_answer(
        self, query: str, result: KnowledgeResult, *, history=None
    ) -> str | None:
        return self.answer

    async def stream_answer(self, query: str, result: KnowledgeResult, *, history=None):
        if self.answer:
            yield self.answer


def make_result(*, low_confidence: bool = False) -> KnowledgeResult:
    """A confident retrieval result with one citation (unless low confidence)."""
    citation = Citation(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title="Leave Policy",
        category="POLICY",
        page=2,
        section_title="Annual Leave",
    )
    return KnowledgeResult(
        grounded_context="Annual leave accrues at 1.5 days per month. (Leave Policy)",
        citations=[] if low_confidence else [citation],
        confidence=0.92,
        chunks=[],
        low_confidence=low_confidence,
    )


class ChatFakeLLM(LLM):
    """Routing prompt -> the route token; rewrite prompt -> a self-contained query.

    Distinguishing by system prompt keeps the fake stateless, so any number
    of turns (routing + rewrite per turn) get sensible replies.
    """

    model = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if "rewrite an HR question" in system:
            return "What is the annual leave policy?"
        return "knowledge"


fake_llm = ChatFakeLLM()


def fake_graph_builder(session, user=None):
    """The graph the chat route runs: real supervisor graph, faked models."""
    from app.agents.supervisor.graph import build_supervisor_graph

    service = FakeKnowledgeService(make_result(), answer="A grounded answer. [1]")
    return build_supervisor_graph(llm=fake_llm, knowledge_service=service)


def low_confidence_graph_builder(session, user=None):
    """A graph whose knowledge node sees no evidence."""
    from app.agents.supervisor.graph import build_supervisor_graph

    service = FakeKnowledgeService(
        make_result(low_confidence=True), answer="should not be used"
    )
    return build_supervisor_graph(llm=FakeLLM("knowledge"), knowledge_service=service)


class RepairingChatLLM(ChatFakeLLM):
    """ChatFakeLLM that also repairs uncited drafts with [N] markers."""

    async def complete(self, system: str, user: str) -> str:
        if "EVERY claim" in system:  # the repair prompt
            return "The policy grants 15 sick days. [1]"
        return await super().complete(system, user)


def claim_tracking_graph_builder(session, user=None):
    """A graph whose answers lack markers, wired to the citation-coverage guard."""
    from app.agents.supervisor.graph import build_supervisor_graph
    from app.safety.output.guards.citations import CitationCoverageCheck
    from app.safety.pipeline import OutputSafetyPipeline

    service = FakeKnowledgeService(make_result(), answer="The policy grants 15 sick days.")
    guard = OutputSafetyPipeline(checks=[CitationCoverageCheck()])
    return build_supervisor_graph(
        llm=RepairingChatLLM(), knowledge_service=service, guard=guard
    )


# --- helpers ---------------------------------------------------------------


async def make_user(db_session, *, email: str, subject: str) -> uuid.UUID:
    """Create a Person + ApplicationUser row and return the user_id."""
    now = get_clock().utc_now()
    person = Person(
        first_name="Test",
        last_name="User",
        email=email,
        created_at=now,
        updated_at=now,
    )
    db_session.add(person)
    await db_session.flush()
    app_user = ApplicationUser(
        person_id=person.person_id,
        external_subject=subject,
        coarse_role="CANDIDATE",
        created_at=now,
        updated_at=now,
    )
    db_session.add(app_user)
    await db_session.flush()
    return app_user.user_id


@dataclass
class ChatEnv:
    """The test harness: client, session factory, and Alice's user_id."""

    client: AsyncClient
    factory: async_sessionmaker
    alice_id: uuid.UUID


@pytest.fixture
async def chat_env(monkeypatch) -> ChatEnv:
    """Purpose-built app: chat router, overridden auth/session, faked graph."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        # Explicit table list: never pull the pgvector knowledge tables into
        # the SQLite schema.
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Person.__table__,
                ApplicationUser.__table__,
                Conversation.__table__,
                ConversationMessage.__table__,
                ConversationWorkflowState.__table__,
            ],
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        alice_id = await make_user(session, email="alice@example.com", subject="sub-1")
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    def override_current_user() -> UserContext:
        return UserContext(
            subject="sub-1",
            email="alice@example.com",
            display_name="Alice",
            coarse_role="CANDIDATE",
        )

    app = FastAPI()
    app.include_router(chat_module.router)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_current_user

    monkeypatch.setattr(chat_module, "build_chat_graph", fake_graph_builder)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield ChatEnv(client=client, factory=factory, alice_id=alice_id)

    await engine.dispose()


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_message_creates_conversation_and_persists(chat_env):
    """A first turn creates the conversation and persists both messages."""
    resp = await chat_env.client.post(
        "/api/chat", json={"message": "What is the annual leave policy?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == "knowledge"
    assert body["message"] == "A grounded answer. [1]"
    assert body["confidence"] == 0.92
    assert body["low_confidence"] is False
    assert body["confidence_applicable"] is True
    assert body["citations"][0]["document_title"] == "Leave Policy"
    conversation_id = uuid.UUID(body["conversation_id"])

    async with chat_env.factory() as session:
        repo = ConversationRepo(session)
        conversation = await repo.get(conversation_id)
        assert conversation is not None
        assert conversation.user_id == chat_env.alice_id
        assert conversation.title == "What is the annual leave policy?"

        messages = await repo.list_messages(conversation_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[1].content == "A grounded answer. [1]"
        assert messages[1].meta == {
            "agent": "knowledge",
            "confidence": 0.92,
            "low_confidence": False,
            "safety": "PASS",
            "confidence_applicable": True,
        }
        assert messages[1].citations[0]["document_title"] == "Leave Policy"


@pytest.mark.asyncio
async def test_leave_turn_marks_confidence_not_applicable(chat_env, monkeypatch):
    """Non-retrieval agents (leave) expose confidence_applicable=False so
    consumers never render a confidence badge for a 0.0 that means
    "not applicable" rather than "very low" — and the flag is persisted."""
    from app.agents.supervisor.graph import build_supervisor_graph

    def leave_graph_builder(session, user=None):
        return build_supervisor_graph(
            llm=FakeLLM("leave"),
            knowledge_service=FakeKnowledgeService(make_result(), answer="A grounded answer. [1]"),
        )

    monkeypatch.setattr(chat_module, "build_chat_graph", leave_graph_builder)

    resp = await chat_env.client.post("/api/chat", json={"message": "my leave balance"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == "leave"
    assert body["confidence"] == 0.0
    assert body["confidence_applicable"] is False
    assert body["citations"] == []

    async with chat_env.factory() as session:
        messages = await ConversationRepo(session).list_messages(uuid.UUID(body["conversation_id"]))
        assert messages[1].meta["agent"] == "leave"
        assert messages[1].meta["confidence"] == 0.0
        assert messages[1].meta["confidence_applicable"] is False


@pytest.mark.asyncio
async def test_followup_hydrates_history_into_graph(chat_env):
    """A follow-up turn passes the prior transcript to the supervisor."""
    first = await chat_env.client.post("/api/chat", json={"message": "How much annual leave do I have?"})
    conversation_id = first.json()["conversation_id"]

    fake_llm.calls.clear()
    second = await chat_env.client.post(
        "/api/chat",
        json={"conversation_id": conversation_id, "message": "what about sick leave?"},
    )
    assert second.status_code == 200

    # The routing prompt for the second turn carries the first turn's history.
    _, routing_prompt = fake_llm.calls[0]
    assert "How much annual leave do I have?" in routing_prompt
    assert "what about sick leave?" in routing_prompt

    async with chat_env.factory() as session:
        messages = await ConversationRepo(session).list_messages(uuid.UUID(conversation_id))
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_blank_message_rejected(chat_env):
    """Whitespace-only messages are rejected."""
    resp = await chat_env.client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_conversation_404(chat_env):
    """Continuing a conversation that does not exist is a 404."""
    resp = await chat_env.client.post(
        "/api/chat",
        json={"conversation_id": str(uuid.uuid4()), "message": "hello again"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_other_users_conversation_404(chat_env):
    """A user cannot continue someone else's conversation (no existence leak)."""
    async with chat_env.factory() as session:
        bob_id = await make_user(session, email="bob@example.com", subject="sub-2")
        bob_conversation = await ConversationRepo(session).create(user_id=bob_id)
        await session.commit()
        bob_conversation_id = bob_conversation.conversation_id

    resp = await chat_env.client.post(
        "/api/chat",
        json={"conversation_id": str(bob_conversation_id), "message": "let me in"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_conversations_scoped_by_user(chat_env):
    """GET /conversations returns only the caller's conversations, newest first."""
    await chat_env.client.post("/api/chat", json={"message": "first question"})
    await chat_env.client.post("/api/chat", json={"message": "second question"})

    async with chat_env.factory() as session:
        bob_id = await make_user(session, email="bob@example.com", subject="sub-2")
        await ConversationRepo(session).create(user_id=bob_id)
        await session.commit()

    resp = await chat_env.client.get("/api/chat/conversations")
    assert resp.status_code == 200
    conversations = resp.json()
    assert len(conversations) == 2
    assert [c["title"] for c in conversations] == ["second question", "first question"]


@pytest.mark.asyncio
async def test_list_messages_oldest_first(chat_env):
    """The transcript endpoint returns messages in conversation order."""
    first = await chat_env.client.post("/api/chat", json={"message": "turn one"})
    conversation_id = first.json()["conversation_id"]
    await chat_env.client.post(
        "/api/chat", json={"conversation_id": conversation_id, "message": "turn two"}
    )

    resp = await chat_env.client.get(f"/api/chat/conversations/{conversation_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["turn one", "turn two"]
    assert messages[1]["citations"][0]["document_title"] == "Leave Policy"
    assert messages[1]["meta"]["agent"] == "knowledge"


@pytest.mark.asyncio
async def test_list_messages_other_user_404(chat_env):
    """Transcripts are private to their owner."""
    async with chat_env.factory() as session:
        bob_id = await make_user(session, email="bob@example.com", subject="sub-2")
        bob_conversation = await ConversationRepo(session).create(user_id=bob_id)
        await session.commit()

    resp = await chat_env.client.get(
        f"/api/chat/conversations/{bob_conversation.conversation_id}/messages"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_success(chat_env):
    """Deleting a conversation cascades message deletions and removes it from listing."""
    first = await chat_env.client.post("/api/chat", json={"message": "turn one"})
    conversation_id = first.json()["conversation_id"]

    # Confirm it exists
    list_resp = await chat_env.client.get("/api/chat/conversations")
    assert any(c["conversation_id"] == conversation_id for c in list_resp.json())

    # Delete it
    del_resp = await chat_env.client.delete(f"/api/chat/conversations/{conversation_id}")
    assert del_resp.status_code == 204

    # Confirm it's gone from list
    list_after = await chat_env.client.get("/api/chat/conversations")
    assert not any(c["conversation_id"] == conversation_id for c in list_after.json())

    # Confirm messages are gone from database
    async with chat_env.factory() as session:
        conversation = await ConversationRepo(session).get(uuid.UUID(conversation_id))
        assert conversation is None
        messages = await ConversationRepo(session).list_messages(uuid.UUID(conversation_id))
        assert messages == []


@pytest.mark.asyncio
async def test_delete_conversation_not_found_404(chat_env):
    """Deleting a non-existent conversation returns 404."""
    resp = await chat_env.client.delete(f"/api/chat/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_other_user_404(chat_env):
    """Deleting another user's conversation returns 404 and preserves the row."""
    async with chat_env.factory() as session:
        bob_id = await make_user(session, email="bob@example.com", subject="sub-2")
        bob_conversation = await ConversationRepo(session).create(user_id=bob_id)
        await session.commit()
        bob_cid = bob_conversation.conversation_id

    resp = await chat_env.client.delete(f"/api/chat/conversations/{bob_cid}")
    assert resp.status_code == 404

    # Bob's conversation still exists
    async with chat_env.factory() as session:
        assert await ConversationRepo(session).get(bob_cid) is not None



# --- SSE helpers -----------------------------------------------------------


async def _sse_events(response) -> list[dict]:
    """Parse the SSE ``data: {json}`` lines of a streaming response."""
    events = []
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_emits_event_sequence(chat_env):
    """The SSE stream carries turn_started -> route -> retrieval -> token -> done."""
    async with chat_env.client.stream(
        "POST", "/api/chat/stream", json={"message": "What is the annual leave policy?"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = await _sse_events(resp)

    types = [e["type"] for e in events]
    assert types == ["turn_started", "route", "retrieval", "token", "done"]

    assert events[0]["conversation_id"]
    assert events[1]["route"] == "knowledge"
    assert events[2]["rewritten_query"] == "What is the annual leave policy?"
    assert events[2]["citations"][0]["document_title"] == "Leave Policy"
    assert events[2]["confidence"] == 0.92
    assert events[3]["text"] == "A grounded answer. [1]"

    done = events[4]
    assert done["message"] == "A grounded answer. [1]"
    assert done["agent"] == "knowledge"
    assert done["confidence"] == 0.92
    assert done["low_confidence"] is False
    assert done["confidence_applicable"] is True
    assert len(done["citations"]) == 1
    assert done["conversation_id"] == events[0]["conversation_id"]

    # The assistant reply was persisted when the stream completed.
    conversation_id = uuid.UUID(done["conversation_id"])
    async with chat_env.factory() as session:
        messages = await ConversationRepo(session).list_messages(conversation_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[1].content == "A grounded answer. [1]"
        assert messages[1].meta == {
            "agent": "knowledge",
            "confidence": 0.92,
            "low_confidence": False,
            "safety": "PASS",
            "confidence_applicable": True,
        }


@pytest.mark.asyncio
async def test_chat_stream_followup_uses_history(chat_env):
    """A streamed follow-up turn still hydrates the prior transcript."""
    first = await chat_env.client.post("/api/chat", json={"message": "How much annual leave do I have?"})
    conversation_id = first.json()["conversation_id"]

    fake_llm.calls.clear()
    async with chat_env.client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": conversation_id, "message": "what about sick leave?"},
    ) as resp:
        events = await _sse_events(resp)

    assert events[-1]["type"] == "done"
    _, routing_prompt = fake_llm.calls[0]
    assert "How much annual leave do I have?" in routing_prompt
    assert "what about sick leave?" in routing_prompt


@pytest.mark.asyncio
async def test_chat_stream_low_confidence_streams_message_not_tokens(chat_env, monkeypatch):
    """Low-confidence retrieval streams an honest message, never tokens."""
    monkeypatch.setattr(chat_module, "build_chat_graph", low_confidence_graph_builder)

    async with chat_env.client.stream(
        "POST", "/api/chat/stream", json={"message": "obscure question"}
    ) as resp:
        events = await _sse_events(resp)

    types = [e["type"] for e in events]
    assert types == ["turn_started", "route", "retrieval", "message", "done"]
    assert "couldn't find enough evidence" in events[3]["text"]
    assert "should not be used" not in events[3]["text"]
    assert events[-1]["low_confidence"] is True
    assert events[-1]["message"] == events[3]["text"]


@pytest.mark.asyncio
async def test_chat_stream_unknown_conversation_404(chat_env):
    """Validation happens before streaming: unknown conversations are HTTP 404."""
    async with chat_env.client.stream(
        "POST",
        "/api/chat/stream",
        json={"conversation_id": str(uuid.uuid4()), "message": "hello"},
    ) as resp:
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_stream_blank_message_422(chat_env):
    """Blank messages are rejected with a proper HTTP error, not an SSE stream."""
    async with chat_env.client.stream("POST", "/api/chat/stream", json={"message": "   "}) as resp:
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_stream_claim_tracking_repairs_uncited_answer(chat_env, monkeypatch):
    """An uncited draft is flagged, repaired with [N] markers, and only the
    verified citation is persisted (claims == citations, end to end)."""
    monkeypatch.setattr(chat_module, "build_chat_graph", claim_tracking_graph_builder)

    async with chat_env.client.stream(
        "POST", "/api/chat/stream", json={"message": "sick leave policy"}
    ) as resp:
        events = await _sse_events(resp)

    done = events[-1]
    assert done["type"] == "done"
    assert done["message"] == "The policy grants 15 sick days. [1]"
    assert len(done["citations"]) == 1
    assert done["citations"][0]["document_title"] == "Leave Policy"

    conversation_id = uuid.UUID(done["conversation_id"])
    async with chat_env.factory() as session:
        messages = await ConversationRepo(session).list_messages(conversation_id)
        assistant = messages[1]
        assert assistant.content == "The policy grants 15 sick days. [1]"
        assert assistant.meta["safety"] == "PASS"
        assert len(assistant.citations) == 1
        assert assistant.citations[0]["document_title"] == "Leave Policy"


@pytest.mark.asyncio
async def test_chat_requires_auth(monkeypatch):
    """Without a token the route rejects the request before any work happens."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Person.__table__, ApplicationUser.__table__, Conversation.__table__, ConversationMessage.__table__],
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    # Note: get_current_user is NOT overridden — the real auth dependency runs.
    app = FastAPI()
    app.include_router(chat_module.router)
    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 401
    await engine.dispose()


@pytest.mark.asyncio
async def test_low_confidence_never_fabricates(chat_env, monkeypatch):
    """Low-confidence retrieval yields an honest refusal in the response."""
    monkeypatch.setattr(chat_module, "build_chat_graph", low_confidence_graph_builder)

    resp = await chat_env.client.post("/api/chat", json={"message": "obscure question"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["low_confidence"] is True
    assert "couldn't find enough evidence" in body["message"]
    assert "should not be used" not in body["message"]
