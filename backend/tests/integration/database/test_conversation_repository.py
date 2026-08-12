"""Integration tests for the conversation repository.

These run against a real PostgreSQL database and are gated on
``TEST_DATABASE_URL``; without it they skip. Conversation tables are plain
SQL (no pgvector columns), so the same behavior is also covered on SQLite by
``tests/unit/repositories/test_conversation.py`` — this suite proves the
contract against the real dialect (JSON columns, UUIDs, FK cascade).
"""

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.domain import conversation as conversation_domain  # noqa: F401
from app.domain import identity  # noqa: F401  (employee table for the FK)
from app.repositories.conversation import ConversationRepo

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
async def db_session():
    """Fresh schema on an ephemeral test DB; skip when no URL is provided."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set; skipping conversation integration test")
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get_conversation(db_session):
    """A created conversation round-trips, with or without an owner."""
    repo = ConversationRepo(db_session)

    owned = await repo.create(employee_id=None)
    assert owned.employee_id is None
    assert owned.title is None

    fetched = await repo.get(owned.conversation_id)
    assert fetched is not None
    assert fetched.conversation_id == owned.conversation_id

    assert await repo.get(uuid.UUID("00000000-0000-0000-0000-000000000000")) is None


@pytest.mark.asyncio
async def test_append_and_order_messages(db_session):
    """Messages get monotonic sequence numbers and come back oldest-first."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create()

    first = await repo.append_message(
        conversation_id=conversation.conversation_id, role="user", content="What is the leave policy?"
    )
    second = await repo.append_message(
        conversation_id=conversation.conversation_id,
        role="assistant",
        content="Annual leave accrues at 1.5 days per month.",
        citations=[{"document_title": "Leave Policy", "page": 2}],
        meta={"confidence": 0.87, "agent": "knowledge"},
    )

    assert first.sequence_no == 1
    assert second.sequence_no == 2
    assert second.citations == [{"document_title": "Leave Policy", "page": 2}]
    assert second.meta == {"confidence": 0.87, "agent": "knowledge"}

    all_messages = await repo.list_messages(conversation.conversation_id)
    assert [m.sequence_no for m in all_messages] == [1, 2]
    assert [m.role for m in all_messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_recent_messages_windows(db_session):
    """recent_messages returns the last n messages, oldest of the window first."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create()
    for i in range(5):
        await repo.append_message(
            conversation_id=conversation.conversation_id, role="user", content=f"msg {i}"
        )

    window = await repo.recent_messages(conversation.conversation_id, n=3)
    assert [m.content for m in window] == ["msg 2", "msg 3", "msg 4"]

    empty = await repo.recent_messages(conversation.conversation_id, n=0)
    assert empty == []


@pytest.mark.asyncio
async def test_title_and_touch(db_session):
    """set_title and touch mutate the conversation row."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create()

    await repo.set_title(conversation.conversation_id, "Leave policy question")
    fetched = await repo.get(conversation.conversation_id)
    assert fetched is not None
    assert fetched.title == "Leave policy question"

    await repo.touch(conversation.conversation_id)
    refreshed = await repo.get(conversation.conversation_id)
    assert refreshed is not None
    assert refreshed.updated_at >= conversation.updated_at


@pytest.mark.asyncio
async def test_messages_cascade_with_conversation(db_session):
    """Deleting a conversation removes its messages (FK ondelete=CASCADE)."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create()
    await repo.append_message(
        conversation_id=conversation.conversation_id, role="user", content="hello"
    )

    await db_session.delete(conversation)
    await db_session.commit()

    assert await repo.list_messages(conversation.conversation_id) == []
