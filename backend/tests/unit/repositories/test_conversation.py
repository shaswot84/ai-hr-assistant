"""Unit tests for the conversation repository on in-memory async SQLite.

Conversation tables are plain SQL (no pgvector columns), so they run on
SQLite via aiosqlite — unlike the pgvector-backed knowledge repository,
which needs a real Postgres and lives in the gated integration suite. Both
suites cover the same contract; this one always runs.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain import conversation as conversation_domain  # noqa: F401
from app.domain.identity import ApplicationUser, Person
from app.repositories.conversation import ConversationRepo
from app.shared.clock import get_clock


@pytest.fixture
async def db_session():
    """In-memory async SQLite with the full domain schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


async def make_user(db_session, *, email: str = "test@example.com") -> uuid.UUID:
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
        external_subject=f"sub-{uuid.uuid4()}",
        coarse_role="CANDIDATE",
        created_at=now,
        updated_at=now,
    )
    db_session.add(app_user)
    await db_session.flush()
    return app_user.user_id


@pytest.mark.asyncio
async def test_create_conversation_round_trip(db_session):
    """A conversation created for a user round-trips."""
    repo = ConversationRepo(db_session)
    user_id = await make_user(db_session)

    conversation = await repo.create(user_id=user_id)

    fetched = await repo.get(conversation.conversation_id)
    assert fetched is not None
    assert fetched.conversation_id == conversation.conversation_id
    assert fetched.user_id == user_id
    assert fetched.title is None
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_get_missing_conversation_returns_none(db_session):
    """get() on an unknown id returns None, not an error."""
    repo = ConversationRepo(db_session)
    assert await repo.get(uuid.UUID("00000000-0000-0000-0000-000000000000")) is None


@pytest.mark.asyncio
async def test_append_message_assigns_sequences(db_session):
    """Each appended message gets the next monotonic sequence number."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create(user_id=await make_user(db_session))

    m1 = await repo.append_message(
        conversation_id=conversation.conversation_id, role="user", content="first"
    )
    m2 = await repo.append_message(
        conversation_id=conversation.conversation_id, role="assistant", content="second"
    )

    assert m1.sequence_no == 1
    assert m2.sequence_no == 2

    messages = await repo.list_messages(conversation.conversation_id)
    assert [m.content for m in messages] == ["first", "second"]


@pytest.mark.asyncio
async def test_citations_and_meta_round_trip(db_session):
    """JSON citation/meta payloads survive the round-trip."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create(user_id=await make_user(db_session))

    message = await repo.append_message(
        conversation_id=conversation.conversation_id,
        role="assistant",
        content="Answer",
        citations=[{"document_title": "Leave Policy"}],
        meta={"confidence": 0.9},
    )

    # Re-read through the repository, not the flushed object, to prove
    # JSON serialization/deserialization works.
    messages = await repo.list_messages(conversation.conversation_id)
    assert messages[0].message_id == message.message_id
    assert messages[0].citations == [{"document_title": "Leave Policy"}]
    assert messages[0].meta == {"confidence": 0.9}


@pytest.mark.asyncio
async def test_recent_messages_returns_last_n_in_order(db_session):
    """recent_messages returns the window oldest-first; ordering is by sequence."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create(user_id=await make_user(db_session))
    for i in range(6):
        await repo.append_message(
            conversation_id=conversation.conversation_id, role="user", content=f"msg {i}"
        )

    window = await repo.recent_messages(conversation.conversation_id, n=2)
    assert [m.content for m in window] == ["msg 4", "msg 5"]

    # A window larger than the conversation returns everything, oldest first.
    full = await repo.recent_messages(conversation.conversation_id, n=100)
    assert [m.content for m in full] == [f"msg {i}" for i in range(6)]


@pytest.mark.asyncio
async def test_messages_are_per_conversation(db_session):
    """Messages never leak across conversations."""
    repo = ConversationRepo(db_session)
    user_id = await make_user(db_session)
    conversation_a = await repo.create(user_id=user_id)
    conversation_b = await repo.create(user_id=user_id)

    await repo.append_message(
        conversation_id=conversation_a.conversation_id, role="user", content="a only"
    )

    assert len(await repo.list_messages(conversation_a.conversation_id)) == 1
    assert await repo.list_messages(conversation_b.conversation_id) == []


@pytest.mark.asyncio
async def test_list_for_user_scopes_by_user(db_session):
    """list_for_user returns only that user's conversations, newest activity first."""
    repo = ConversationRepo(db_session)
    alice = await make_user(db_session, email="alice@example.com")
    bob = await make_user(db_session, email="bob@example.com")

    alice_first = await repo.create(user_id=alice)
    # Bob's conversation is never visible to Alice.
    await repo.create(user_id=bob)
    # Distinct timestamps so the activity ordering below is unambiguous.
    await asyncio.sleep(0.005)
    alice_second = await repo.create(user_id=alice)

    listed = await repo.list_for_user(alice)
    assert [c.conversation_id for c in listed] == [
        alice_second.conversation_id,
        alice_first.conversation_id,
    ]

    # Touching the older conversation moves it to the top of Alice's list.
    await asyncio.sleep(0.005)
    await repo.touch(alice_first.conversation_id)
    listed_after = await repo.list_for_user(alice)
    assert [c.conversation_id for c in listed_after] == [
        alice_first.conversation_id,
        alice_second.conversation_id,
    ]


@pytest.mark.asyncio
async def test_sequence_continues_across_messages(db_session):
    """Sequence numbers continue after a gap (e.g. concurrent appends)."""
    repo = ConversationRepo(db_session)
    conversation = await repo.create(user_id=await make_user(db_session))

    await repo.append_message(
        conversation_id=conversation.conversation_id, role="user", content="one"
    )
    # Simulate a gap: write a message with an explicit high sequence number.
    from app.domain.conversation import ConversationMessage

    now = get_clock().utc_now()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.conversation_id,
            sequence_no=10,
            role="user",
            content="gap",
            created_at=now,
        )
    )
    await db_session.flush()

    next_msg = await repo.append_message(
        conversation_id=conversation.conversation_id, role="assistant", content="after gap"
    )
    assert next_msg.sequence_no == 11
