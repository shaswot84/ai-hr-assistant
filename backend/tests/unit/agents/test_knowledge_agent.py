"""Unit tests for the knowledge agent (rewrite -> retrieve -> stream -> verify).

Covers query rewriting, token streaming, honest refusals, claim tracking
(``[N]`` markers -> verified citations), and the output-safety wiring
(block -> refusal, flagged -> one repair pass). Uses fake LLM / knowledge
service / guard so nothing touches a model server or a database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.knowledge_agent.agent import (
    KnowledgeTurn,
    balance_relevant,
    fallback_message,
    renumber_markers,
    rewrite_query,
    stream_knowledge_turn,
    verified_citations,
)
from app.contracts.auth import UserContext
from app.knowledge.contracts import Citation, KnowledgeResult
from app.knowledge.markers import strip_invalid_markers
from app.model_gateway.interfaces import LLM
from app.safety.contracts import (
    FindingSeverity,
    GuardFinding,
    GuardResult,
    GuardVerdict,
)
from app.safety.output.guards.citations import CitationCoverageCheck
from app.safety.pipeline import OutputSafetyPipeline


class FakeLLM(LLM):
    """An LLM stub with a canned completion."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


class ScriptedLLM(LLM):
    """An LLM stub returning responses in order (routing, then repair, ...)."""

    model = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0) if self.responses else ""


class FakeKnowledgeService:
    """A KnowledgeService stub capturing what the node asks it."""

    def __init__(
        self,
        result: KnowledgeResult,
        answer: str | None = "Grounded answer from the policy. [1]",
    ) -> None:
        self.result = result
        self.answer = answer
        self.retrieve_queries: list[str] = []
        self.retrieve_kwargs: list[dict] = []
        self.stream_queries: list[str] = []
        self.stream_histories: list[str | None] = []

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        self.retrieve_queries.append(query)
        self.retrieve_kwargs.append(kwargs)
        return self.result

    async def stream_answer(self, query: str, result: KnowledgeResult, *, history=None):
        self.stream_queries.append(query)
        self.stream_histories.append(history)
        if self.answer:
            yield self.answer


class FakeGuard:
    """A guard stub returning a canned GuardResult."""

    def __init__(self, result: GuardResult) -> None:
        self.result = result

    async def guard(self, context) -> GuardResult:
        return self.result


class _FakeLeaveType:
    """A LeaveType-shaped stub (get_leave_balance reads ``.leave_name``)."""

    def __init__(self, name: str) -> None:
        self.leave_name = name


class FakeLeaveService:
    """A LeaveService stub exposing the two methods the balance enrichment
    calls: ``list_leave_types`` (for mentioned_leave_type) and
    ``list_my_balance`` (for get_leave_balance)."""

    def __init__(self, rows: list[dict] | None = None, types: list[_FakeLeaveType] | None = None) -> None:
        self.rows = rows or [
            {
                "leave_type": _FakeLeaveType("Sick Leave"),
                "year": 2026,
                "allocated_days": Decimal(10),
                "used_days": Decimal("5.5"),
                "remaining_days": Decimal("4.5"),
            }
        ]
        self.types = types or [_FakeLeaveType("Sick Leave")]

    def list_leave_types(self):
        return self.types

    def list_my_balance(self, actor, year=None):
        return self.rows


def _employee() -> UserContext:
    return UserContext(subject="emp-1", email="emp@x.com", display_name="Emp", coarse_role="EMPLOYEE")


def make_result(*, low_confidence: bool = False, confidence: float = 0.9) -> KnowledgeResult:
    """A retrieval result with one citation (unless low confidence)."""
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
        confidence=confidence,
        chunks=[],
        low_confidence=low_confidence,
    )


class EventCollector:
    """Captures the events the turn streams through its writer."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


# --- query rewriting ------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_query_uses_llm():
    """With an LLM, a context-dependent follow-up becomes self-contained."""
    llm = FakeLLM("What is the sick leave policy?")
    history = [
        HumanMessage(content="How much annual leave do I have?"),
        AIMessage(content="You have 15 days remaining."),
    ]

    rewritten = await rewrite_query(llm, "what about sick leave?", history)
    assert rewritten == "What is the sick leave policy?"

    _, user_prompt = llm.calls[0]
    assert "How much annual leave do I have?" in user_prompt
    assert "what about sick leave?" in user_prompt


@pytest.mark.asyncio
async def test_rewrite_query_without_llm_returns_query():
    """No LLM configured -> the raw query is used for retrieval."""
    assert await rewrite_query(None, "what about sick leave?", []) == "what about sick leave?"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_on_failure():
    """A failing rewrite LLM never breaks retrieval."""

    class BrokenLLM(FakeLLM):
        async def complete(self, system: str, user: str) -> str:
            raise RuntimeError("model down")

    assert await rewrite_query(BrokenLLM("x"), "the original question", []) == "the original question"


# --- turn orchestration + claim tracking ----------------------------------


@pytest.mark.asyncio
async def test_stream_knowledge_turn_rewrites_then_retrieves():
    """The turn retrieves on the REWRITTEN query, streams, and verifies claims."""
    llm = FakeLLM("What is the sick leave policy?")
    service = FakeKnowledgeService(make_result())
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="what about sick leave?", history=[], writer=writer
    )

    assert service.retrieve_queries == ["What is the sick leave policy?"]
    assert service.stream_queries == ["What is the sick leave policy?"]

    # Streamed events: retrieval metadata first, then the answer token.
    types = [e["type"] for e in writer.events]
    assert types == ["retrieval", "token"]
    assert writer.events[0]["rewritten_query"] == "What is the sick leave policy?"
    assert writer.events[0]["result"] is service.result

    # The answer cites [1] -> exactly the one retrieved citation is verified.
    assert state_update["answer"] == "Grounded answer from the policy. [1]"
    assert state_update["agent"] == "knowledge"
    assert state_update["confidence"] == 0.9
    assert state_update["safety"] == "PASS"
    assert [c.document_title for c in state_update["citations"]] == ["Leave Policy"]
    assert state_update["messages"][-1].content == "Grounded answer from the policy. [1]"


# --- role-based access control --------------------------------------------


@pytest.mark.asyncio
async def test_stream_knowledge_turn_forwards_role_access():
    """The turn retrieves with the actor's role access tag."""
    service = FakeKnowledgeService(make_result())

    await stream_knowledge_turn(
        service=service, llm=None, query="leave policy", history=[], writer=EventCollector()
    )
    assert service.retrieve_kwargs[-1]["access_roles"] == ["VISITOR"]

    candidate = UserContext(
        subject="c-1", email="c@x.com", display_name="C", coarse_role="CANDIDATE"
    )
    await stream_knowledge_turn(
        service=service,
        llm=None,
        query="leave policy",
        history=[],
        writer=EventCollector(),
        actor=candidate,
    )
    assert service.retrieve_kwargs[-1]["access_roles"] == ["CANDIDATE"]

    hr = UserContext(subject="h-1", email="h@x.com", display_name="H", coarse_role="HR_ADMIN")
    await stream_knowledge_turn(
        service=service,
        llm=None,
        query="leave policy",
        history=[],
        writer=EventCollector(),
        actor=hr,
    )
    assert service.retrieve_kwargs[-1]["access_roles"] is None


@pytest.mark.asyncio
async def test_stream_knowledge_turn_replies_denial_for_restricted():
    """A query matching only inaccessible documents gets a deterministic
    denial reply naming the allowed roles — never an LLM answer."""
    from app.knowledge.contracts import RestrictedDocument

    result = make_result()
    result = KnowledgeResult(
        grounded_context="",
        citations=[],
        confidence=0.0,
        chunks=[],
        low_confidence=True,
        restricted=[
            RestrictedDocument(title="Compensation Bands", allowed_roles=["HR_ADMIN", "EMPLOYEE"]),
        ],
    )
    service = FakeKnowledgeService(result)
    writer = EventCollector()

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="what are the compensation bands",
        history=[],
        writer=writer,
        actor=_employee(),
    )

    assert state["answer"] == "You cannot access this file. Only EMPLOYEE, HR_ADMIN can see it."
    assert state["citations"] == []
    assert state["safety"] == "PASS"
    assert service.stream_queries == []  # never generated from restricted content


@pytest.mark.asyncio
async def test_stream_knowledge_turn_empty_knowledge_base_message():
    """An empty knowledge base yields a deterministic 'no documents' reply,
    never an LLM generation or a generic failure."""
    from app.agents.knowledge_agent.agent import EMPTY_KB_MESSAGE

    result = KnowledgeResult(grounded_context="", empty_knowledge_base=True)
    service = FakeKnowledgeService(result)
    writer = EventCollector()

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="what is the leave policy",
        history=[],
        writer=writer,
    )

    assert state["answer"] == EMPTY_KB_MESSAGE
    assert state["citations"] == []
    assert state["safety"] == "PASS"
    assert service.stream_queries == []  # never generated for an empty KB
    assert writer.events[-1] == {"type": "message", "text": EMPTY_KB_MESSAGE}
    assert [e["type"] for e in writer.events] == ["retrieval", "message"]


# --- balance reconciliation (policy + real balance) -------------------------


def test_balance_relevant_matrix():
    """Only amount/entitlement phrasing combined with leave vocabulary is
    balance-relevant — definitional and procedural questions are not."""
    assert balance_relevant("how many sick days do i get")
    assert balance_relevant("how much annual leave am I entitled to")
    assert balance_relevant("what is my sick leave balance")
    assert balance_relevant("how many days of casual leave do I have")
    assert not balance_relevant("what is the annual leave policy")
    assert not balance_relevant("when can I take annual leave")
    assert not balance_relevant("what is the dress code")
    assert not balance_relevant("how many days until payroll")


@pytest.mark.asyncio
async def test_stream_knowledge_turn_appends_employee_balance():
    """A balance-relevant employee question gets the REAL balance appended to
    the policy answer deterministically and injected into the generation
    context, so the policy number and actual remaining days travel together."""
    service = FakeKnowledgeService(make_result())
    writer = EventCollector()

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="how many sick days do i get",
        history=[],
        writer=writer,
        actor=_employee(),
        leave_service=FakeLeaveService(),
    )

    assert state["answer"] == (
        "Grounded answer from the policy. [1]\n\n"
        "Your leave balance:\nSick Leave: 4.5 of 10 days remaining"
    )
    assert state["messages"][-1].content == state["answer"]
    # The generation prompt saw the authoritative balance (labeled so the LLM
    # never attaches citation markers to balance numbers).
    assert "CURRENT LEAVE BALANCE" in service.stream_histories[0]
    assert "Sick Leave: 4.5 of 10 days remaining" in service.stream_histories[0]


@pytest.mark.asyncio
async def test_stream_knowledge_turn_skips_balance_for_candidate():
    """Non-employees (candidates / HR admins) have no leave of their own — no
    balance block is appended."""
    service = FakeKnowledgeService(make_result())
    actor = UserContext(subject="cand-1", email="c@x.com", display_name="C", coarse_role="CANDIDATE")

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="how many sick days do i get",
        history=[],
        writer=EventCollector(),
        actor=actor,
        leave_service=FakeLeaveService(),
    )

    assert state["answer"] == "Grounded answer from the policy. [1]"
    assert "Your leave balance:" not in state["answer"]


@pytest.mark.asyncio
async def test_stream_knowledge_turn_skips_balance_for_non_balance_query():
    """A definitional question mentions leave but is not balance-relevant — no
    balance fetch, no append."""
    service = FakeKnowledgeService(make_result())

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="what is the annual leave policy",
        history=[],
        writer=EventCollector(),
        actor=_employee(),
        leave_service=FakeLeaveService(),
    )

    assert state["answer"] == "Grounded answer from the policy. [1]"
    assert "Your leave balance:" not in state["answer"]


@pytest.mark.asyncio
async def test_refusal_still_appends_balance():
    """Even when the KB has no evidence, the real balance is still a true
    answer to the balance half of the question — it is appended to the
    honest refusal."""
    service = FakeKnowledgeService(make_result(low_confidence=True))

    state = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten"),
        query="how many sick days do i get",
        history=[],
        writer=EventCollector(),
        actor=_employee(),
        leave_service=FakeLeaveService(),
    )

    assert "couldn't find enough evidence" in state["answer"]
    assert "Your leave balance:\nSick Leave: 4.5 of 10 days remaining" in state["answer"]
    assert state["citations"] == []


@pytest.mark.asyncio
async def test_stream_knowledge_turn_includes_history_in_generation():
    """The generation prompt receives a compact history block."""
    service = FakeKnowledgeService(make_result())
    writer = EventCollector()
    history = [HumanMessage(content="How much annual leave do I have?")]

    await stream_knowledge_turn(
        service=service, llm=FakeLLM("rewritten q"), query="what about sick leave?",
        history=history, writer=writer,
    )

    assert service.stream_histories == ["User: How much annual leave do I have?"]


@pytest.mark.asyncio
async def test_verified_citations_parses_markers():
    """Only markers present in the text count, and only within the retrieved set."""
    c1, c2 = make_result().citations[0], make_result().citations[0]
    result = KnowledgeResult(
        grounded_context="",
        citations=[c1, c2],
        confidence=0.9,
        chunks=[],
        low_confidence=False,
    )
    text = "Annual leave accrues at 1.5 days [1]. Sick leave is separate [2]."

    verified = verified_citations(text, result.citations)
    assert [c.document_title for c in verified] == ["Leave Policy", "Leave Policy"]

    # Out-of-range marker [5] is never verified; an uncited answer verifies nothing.
    assert verified_citations("No markers at all.", result.citations) == []
    assert verified_citations("Claims a source [5].", result.citations) == []


@pytest.mark.asyncio
async def test_strip_invalid_markers():
    """Markers for never-retrieved sources are removed from the text."""
    stripped = strip_invalid_markers("One claim [1] and a bogus one [9].", citation_count=1)
    assert stripped == "One claim [1] and a bogus one ."

    # Comma / range forms no longer slip through the single-number regex.
    assert strip_invalid_markers("Claims [1, 9] and [7].", citation_count=1) == "Claims [1] and ."
    assert strip_invalid_markers("Range [1-3].", citation_count=1) == "Range [1]."


@pytest.mark.asyncio
async def test_renumber_markers_dense():
    """Markers are renumbered densely against the kept citation set."""
    # 5 chunks grounded, only 1, 2 and 5 are actually cited -> markers 1..3.
    assert renumber_markers("See [1] and [5].", [1, 2, 5]) == "See [1] and [3]."
    assert renumber_markers("[1, 5]", [1, 2, 5]) == "[1, 3]"
    # Out-of-range markers vanish; an empty group is removed entirely.
    assert renumber_markers("Says [7].", [1, 2, 5]) == "Says ."
    # A kept contiguous span stays a range; ranges of kept indexes stay valid.
    assert renumber_markers("[1-5]", [1, 2, 5]) == "[1-3]"
    # Cross-bracket range: both sides map monotonically.
    assert renumber_markers("([1] - [5])", [1, 2, 5]) == "([1] - [3])"


@pytest.mark.asyncio
async def test_verified_citations_parses_range_markers():
    """Range/comma markers count toward verification too."""
    c1, c2 = make_result().citations[0], make_result().citations[0]
    result = KnowledgeResult(
        grounded_context="",
        citations=[c1, c2],
        confidence=0.9,
        chunks=[],
        low_confidence=False,
    )
    assert verified_citations("Both blocks [1, 2].", result.citations) == [c1, c2]
    assert verified_citations("Range [1-2].", result.citations) == [c1, c2]
    assert verified_citations("Out of range [3].", result.citations) == []


@pytest.mark.asyncio
async def test_low_confidence_streams_honest_message():
    """Low-confidence retrieval streams a message, never tokens or a fake answer."""
    service = FakeKnowledgeService(make_result(low_confidence=True), answer="should not be used")
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=FakeLLM("rewritten"), query="q", history=[], writer=writer
    )

    assert [e["type"] for e in writer.events] == ["retrieval", "message"]
    assert "couldn't find enough evidence" in writer.events[1]["text"]
    assert "should not be used" not in writer.events[1]["text"]
    assert "couldn't find enough evidence" in state_update["answer"]
    assert state_update["citations"] == []
    assert state_update["safety"] == "PASS"


@pytest.mark.asyncio
async def test_no_answer_with_evidence_serves_grounded_context():
    """Evidence found but no generated answer -> grounded-context message."""
    service = FakeKnowledgeService(make_result(), answer=None)
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=None, query="annual leave accrual", history=[], writer=writer
    )

    assert [e["type"] for e in writer.events] == ["retrieval", "message"]
    assert state_update["answer"] == "Annual leave accrues at 1.5 days per month. (Leave Policy)"
    # The fallback text carries no [N] markers -> nothing is "verified".
    assert state_update["citations"] == []


# --- output-safety wiring --------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_answer_becomes_refusal():
    """A BLOCK verdict (e.g. evidence gate) replaces the answer with a refusal."""
    guard = FakeGuard(
        GuardResult(
            verdict=GuardVerdict.BLOCKED,
            response="should not be served",
            findings=[
                GuardFinding(
                    guard="evidence",
                    severity=FindingSeverity.BLOCK,
                    message="refusing to answer without sufficient evidence",
                )
            ],
        )
    )
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=FakeKnowledgeService(make_result(), answer="should not be served"),
        llm=FakeLLM("rewritten"),
        query="q",
        history=[],
        writer=writer,
        guard=guard,
    )

    assert "couldn't find enough evidence" in state_update["answer"]
    assert "should not be served" not in state_update["answer"]
    assert state_update["citations"] == []
    assert state_update["safety"] == GuardVerdict.BLOCKED.value


@pytest.mark.asyncio
async def test_flagged_answer_gets_one_repair_pass():
    """Claims without markers -> FLAGGED -> one repair pass restores traceability."""
    guard = OutputSafetyPipeline(checks=[CitationCoverageCheck()])
    # First LLM call rewrites the query; second repairs the draft with markers.
    llm = ScriptedLLM(["What is the sick leave policy?", "The policy grants 15 sick days. [1]"])
    writer = EventCollector()
    service = FakeKnowledgeService(make_result(), answer="The policy grants 15 sick days.")

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="sick leave", history=[], writer=writer, guard=guard
    )

    # The repaired (marker-ful) answer wins and its citation is verified.
    assert state_update["answer"] == "The policy grants 15 sick days. [1]"
    assert [c.document_title for c in state_update["citations"]] == ["Leave Policy"]
    assert state_update["safety"] == "PASS"
    # Two LLM calls: rewrite + repair.
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_flagged_answer_keeps_draft_when_repair_fails():
    """If the repair adds no markers, the draft is kept but nothing is verified."""
    guard = OutputSafetyPipeline(checks=[CitationCoverageCheck()])
    # The "repair" returns a string with no markers -> discarded.
    llm = ScriptedLLM(["What is the sick leave policy?", "still no markers here"])
    writer = EventCollector()
    service = FakeKnowledgeService(make_result(), answer="The policy grants 15 sick days.")

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="sick leave", history=[], writer=writer, guard=guard
    )

    assert state_update["answer"] == "The policy grants 15 sick days."
    assert state_update["citations"] == []
    assert state_update["safety"] == GuardVerdict.FLAGGED_FOR_REVIEW.value


@pytest.mark.asyncio
async def test_pii_redaction_is_applied():
    """A REDACTED verdict serves the sanitized response."""
    from app.safety.output.guards.pii import PIIRedactionCheck

    guard = OutputSafetyPipeline(checks=[PIIRedactionCheck()])
    writer = EventCollector()
    service = FakeKnowledgeService(
        make_result(), answer="Email support at john@example.com for help. [1]"
    )

    state_update = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten q"),
        query="who do I contact",
        history=[],
        writer=writer,
        guard=guard,
    )

    assert "john@example.com" not in state_update["answer"]
    assert "[REDACTED]" in state_update["answer"]
    # Redaction happens after streaming: the writer saw the raw token.
    assert "john@example.com" in writer.events[1]["text"]


@pytest.mark.asyncio
async def test_fallback_message():
    """fallback_message distinguishes low-confidence refusal from grounded context."""
    low = KnowledgeTurn(
        original_query="q",
        rewritten_query="q",
        result=make_result(low_confidence=True),
        answer=None,
    )
    assert "couldn't find enough evidence" in fallback_message(low)

    ok = KnowledgeTurn(
        original_query="q",
        rewritten_query="q",
        result=make_result(),
        answer=None,
    )
    assert fallback_message(ok) == "Annual leave accrues at 1.5 days per month. (Leave Policy)"
