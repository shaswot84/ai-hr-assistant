"""End-to-end tests: the real supervisor graph with a wired leave node.

These tests drive ``build_supervisor_graph`` exactly the way ``chat.py``
does — routing fake for the supervisor, scripted cooperative model for the
leave agent, real ``LeaveService`` against the test SQLite DB, real actor
identities — and assert on the durable outcome (LeaveRequest rows, workflow
rows, staged confirmations). They are "end to end" in the sense that every
layer between the user message and the DB write is exercised: routing ->
leave node -> deterministic interception -> model path -> tool execution ->
workflow persistence. The only things not exercised are Ollama itself and
the HTTP/SSE transport (covered in test_chat_api.py).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import func, select

from app.agents.leave_agent.state import SessionStore
from app.agents.supervisor.graph import build_supervisor_graph
from app.capabilities.leave import LeaveService
from app.domain.conversation import Conversation, ConversationWorkflowState
from app.domain.leave import LeaveRequest
from app.knowledge.contracts import Citation, KnowledgeResult
from app.model_gateway.interfaces import LLM
from app.repositories.workflow_state import STATUS_COMPLETED, WorkflowStateRepo
from app.services.identity import IdentityService
from app.shared.clock import get_clock

# --- fakes (same shapes as the unit suites) --------------------------------


class FakeLLM(LLM):
    """An LLM stub with a canned completion (same reply for every call)."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, system: str, user: str) -> str:
        return self.response


class FakeKnowledgeService:
    """A KnowledgeService stub returning a fixed retrieval result."""

    def __init__(self, result: KnowledgeResult, answer: str | None = "A grounded answer. [1]") -> None:
        self.result = result
        self.answer = answer

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        return self.result

    async def generate_answer(self, query: str, result: KnowledgeResult, *, history=None) -> str | None:
        return self.answer

    async def stream_answer(self, query: str, result: KnowledgeResult, *, history=None):
        if self.answer:
            yield self.answer


def make_result() -> KnowledgeResult:
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
        citations=[citation],
        confidence=0.92,
        chunks=[],
        low_confidence=False,
    )


# --- scripted cooperative model for the leave agent -------------------------

_STAGED_RE = re.compile(
    r"STAGED ACTION AWAITING CONFIRMATION:\ntool: (\w+)\nargs: (\{.*\})\n",
    re.DOTALL,
)
_EMPLOYEE_MSG_RE = re.compile(r"EMPLOYEE'S NEW MESSAGE:\n(.*)$", re.DOTALL)

_TYPE_HINTS = {
    "annual": "Annual Leave",
    "sick": "Sick Leave",
    "casual": "Casual Leave",
    "causal": "Casual Leave",
    "unpaid": "Unpaid Leave",
}


def _extract_user_message(user_prompt: str) -> str:
    match = _EMPLOYEE_MSG_RE.search(user_prompt)
    return match.group(1).strip() if match else ""


def _extract_staged(user_prompt: str) -> tuple[str, dict] | None:
    match = _STAGED_RE.search(user_prompt)
    if match is None:
        return None
    try:
        return match.group(1), json.loads(match.group(2))
    except json.JSONDecodeError:
        return None


def _is_confirmation(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in ("yes", "confirm", "go ahead", "sure", "ok"))


def _guess_type(message: str) -> str | None:
    for hint, name in _TYPE_HINTS.items():
        if hint in message:
            return name
    return None


class ScriptedChatProvider:
    """A cooperative model stand-in for the leave agent.

    Behaves like a compliant leave-agent model: confirms a staged write
    action verbatim on a yes, calls get_leave_balance for a request with a
    named type (rule 10) and for balance questions, calls list_leave_types
    for a request start without a type, and acknowledges otherwise.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> dict:
        self.calls += 1
        self.prompts.append(user_prompt)
        user_message = _extract_user_message(user_prompt)
        lowered = user_message.lower()

        staged = _extract_staged(user_prompt)
        if staged is not None and _is_confirmation(user_message):
            tool, args = staged
            return {"reply": "Done.", "action": "call_tool", "tool": tool, "args": args}

        code_match = re.search(r"EMP-[A-Z0-9-]+", user_message, re.IGNORECASE)
        if code_match is not None:
            # A manager asking about another employee's balance uses the HR tool.
            return {
                "reply": "Checking that balance.",
                "action": "call_tool",
                "tool": "get_employee_leave_balance",
                "args": {"employee_code": code_match.group(0).upper()},
            }

        if any(word in lowered for word in ("balance", "remaining", "how much", "left")):
            return {"reply": "Checking your balance.", "action": "call_tool", "tool": "get_leave_balance", "args": {}}

        if any(word in lowered for word in ("apply", "want", "request", "take", "book", "get", "avail")):
            mentioned = _guess_type(user_message)
            if mentioned is not None:
                return {
                    "reply": "Checking that type's balance.",
                    "action": "call_tool",
                    "tool": "get_leave_balance",
                    "args": {"leave_type_name": mentioned},
                }
            return {"reply": "Let me pull up the leave types.", "action": "call_tool", "tool": "list_leave_types", "args": {}}

        if "type" in lowered:
            return {"reply": "Here are the types.", "action": "call_tool", "tool": "list_leave_types", "args": {}}

        return {"reply": "How can I help with your leave?", "action": "reply", "tool": None, "args": {}}


class AmbiguousFallbackProvider(ScriptedChatProvider):
    """A model that wrongly falls back to list_leave_types on an ambiguous
    message — used to prove the deterministic guard catches it."""

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return {"reply": "Let me pull up the leave types.", "action": "call_tool", "tool": "list_leave_types", "args": {}}


class WrongArgsProvider(ScriptedChatProvider):
    """A model that confirms a staged submit with WRONG dates — proves the
    confirmation gate blocks a mismatched execution."""

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        staged = _extract_staged(kwargs["user_prompt"])
        user_message = _extract_user_message(kwargs["user_prompt"])
        if staged is not None and _is_confirmation(user_message):
            tool, args = staged
            wrong = dict(args)
            if "start_date" in wrong:
                wrong["start_date"] = "2099-01-01"
            return {"reply": "Submitting.", "action": "call_tool", "tool": tool, "args": wrong}
        return await super().complete_json(**kwargs)


# --- DB seeding helpers -----------------------------------------------------


def _create_leave_type(svc, actor, *, name="Annual Leave", default_days=Decimal(20)):
    return svc.create_leave_type(
        actor,
        leave_name=name,
        description="Planned time off.",
        default_days=default_days,
        requires_approval=True,
        is_paid=True,
        max_consecutive_days=None,
    )


def _user_id(db, actor) -> uuid.UUID:
    return IdentityService(db)._get_app_user(actor).user_id


def _seed_conversation(db, actor) -> uuid.UUID:
    now = get_clock().utc_now()
    conversation = Conversation(user_id=_user_id(db, actor), title="E2E", created_at=now, updated_at=now)
    db.add(conversation)
    db.flush()
    return conversation.conversation_id


def _seed_pending_request(svc, manager_ctx, employee_ctx) -> LeaveRequest:
    leave_type = _create_leave_type(svc, manager_ctx)
    today = get_clock().today()
    return svc.request_leave(
        employee_ctx,
        leave_type_id=leave_type.leave_type_id,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=6),
        reason=None,
    )


def _request_count(db) -> int:
    return db.scalar(select(func.count(LeaveRequest.leave_request_id)))


def _workflow_row(db, conversation_id: uuid.UUID, actor):
    return WorkflowStateRepo(db).get_active(conversation_id, _user_id(db, actor))


# --- the harness ------------------------------------------------------------


class LeaveChatE2E:
    """Drive the real supervisor graph the way chat.py does."""

    def __init__(
        self,
        db,
        actor,
        *,
        route: str = "leave",
        provider: ScriptedChatProvider | None = None,
        store: SessionStore | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> None:
        self.db = db
        self.actor = actor
        self.provider = provider or ScriptedChatProvider()
        self.store = store or SessionStore()
        self.conversation_id = conversation_id or _seed_conversation(db, actor)
        db.commit()
        self.graph = build_supervisor_graph(
            llm=FakeLLM(route),
            knowledge_service=FakeKnowledgeService(make_result()),
            leave_actor=actor,
            leave_store=self.store,
            leave_chat_provider=self.provider,
            leave_service=LeaveService(db),
        )
        self.history: list = []

    async def turn(self, message: str) -> dict:
        """One user message through the whole graph; returns the final state."""
        state = await self.graph.ainvoke(
            {
                "messages": list(self.history),
                "current_query": message,
                "conversation_id": str(self.conversation_id),
            }
        )
        self.history.append(HumanMessage(content=message))
        self.history.append(AIMessage(content=state["answer"]))
        return state


# --- employee self-service --------------------------------------------------


@pytest.mark.asyncio
async def test_employee_full_submit_roundtrip(db, manager_context, employee_context):
    """The complete happy path end to end: apply with relative dates ->
    draft completed deterministically -> staged -> confirmed -> real
    PENDING LeaveRequest row in the DB."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("i want to apply for annual leave tomorrow")
    assert state["agent"] == "leave"
    assert "To which date would you like to end?" in state["answer"]
    assert harness.provider.calls == 0  # dates are resolved without the model

    state = await harness.turn("for 3 days")
    assert "Submit an Annual Leave request" in state["answer"]
    assert harness.provider.calls == 0  # draft completion is deterministic

    state = await harness.turn("yes")
    assert harness.provider.calls == 1  # the model only confirmed
    assert "submitted" in state["answer"].lower()
    assert "PENDING" in state["answer"]

    request = db.scalar(select(LeaveRequest))
    assert request is not None
    assert request.status == "PENDING"
    assert request.start_date == get_clock().today() + timedelta(days=1)
    assert request.end_date == get_clock().today() + timedelta(days=3)


@pytest.mark.asyncio
async def test_balance_question_answered_deterministically(db, manager_context, employee_context):
    """A balance question is answered deterministically from the employee's
    real balance — no model call, no draft, no request-start question."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("how much annual leave do i have")

    assert state["agent"] == "leave"
    assert harness.provider.calls == 0
    assert "Annual Leave: 20.0 of 20.0 days remaining" in state["answer"]
    assert "What dates" not in state["answer"]  # a balance question is not a request start
    assert _workflow_row(db, harness.conversation_id, employee_context) is None


@pytest.mark.asyncio
async def test_request_intent_without_type_lists_then_continues(db, manager_context, employee_context):
    """'i want to apply for leave' -> model lists types -> deterministic
    draft takes over and the request completes and submits."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave")
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("i want to apply for leave")
    assert harness.provider.calls == 1
    # The raw type-list dump is suppressed for a request start — the answer
    # is the type question alone, never "Available leave types: ...".
    assert "Available leave types:" not in state["answer"]
    assert "Which leave type would you like to take?" in state["answer"]

    state = await harness.turn("annual leave")
    assert "From which date would you like to start?" in state["answer"]
    assert harness.provider.calls == 1  # type resolution is deterministic

    state = await harness.turn("tomorrow")
    assert "To which date would you like to end?" in state["answer"]

    state = await harness.turn("for 2 days")
    assert "Submit an Annual Leave request" in state["answer"]

    state = await harness.turn("yes")
    assert "submitted" in state["answer"].lower()
    assert _request_count(db) == 1


@pytest.mark.asyncio
async def test_ambiguous_message_does_not_dump_type_list(db, manager_context, employee_context):
    """A model that falls back to list_leave_types on an ambiguous message
    must NOT dump 'Available leave types: ...' — the deterministic guard
    asks what action the user wants instead."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave")
    harness = LeaveChatE2E(db, employee_context, provider=AmbiguousFallbackProvider())

    state = await harness.turn("what should i do")

    assert harness.provider.calls == 1
    assert "Available leave types:" not in state["answer"]
    assert "what would you like to do" in state["answer"]
    assert _workflow_row(db, harness.conversation_id, employee_context) is None


@pytest.mark.asyncio
async def test_types_question_list_is_the_answer(db, manager_context, employee_context):
    """A direct question about types is answered by the list itself — no
    'which type' follow-up, no draft."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave")
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("which leave types are there")

    assert harness.provider.calls == 1
    assert "Available leave types:" in state["answer"]
    assert "Which leave type would you like to take?" not in state["answer"]
    assert _workflow_row(db, harness.conversation_id, employee_context) is None


@pytest.mark.asyncio
async def test_request_words_with_relative_date_need_no_model(db, manager_context, employee_context):
    """New request-intent words ('get'/'take'/'avail'/'book') plus a
    relative date open the draft deterministically — no model call."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("can i get leave for next sunday")

    assert harness.provider.calls == 0
    assert "Which leave type would you like to take?" in state["answer"]
    row = _workflow_row(db, harness.conversation_id, employee_context)
    assert row is not None
    assert row.draft_request["start_date"] is not None


@pytest.mark.asyncio
async def test_cancel_by_reference_roundtrip(db, manager_context, employee_context):
    """Cancel by LR reference -> staged -> confirmed -> CANCELLED row."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn(f"please cancel request {request.request_number}")
    assert harness.provider.calls == 0  # reference writes are deterministic
    assert f"Cancel leave request {request.request_number}" in state["answer"]

    state = await harness.turn("yes")
    assert harness.provider.calls == 1
    assert "cancelled" in state["answer"].lower()
    db.expire_all()
    refreshed = svc.get_my_request_by_reference(employee_context, request.request_number)
    assert refreshed.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_without_reference_lists_and_picks(db, manager_context, employee_context):
    """Cancel without a reference lists what CAN be cancelled, and the
    number then stages + executes the cancel."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("cancel my leave request")
    assert harness.provider.calls == 0
    assert "Which request would you like to cancel?" in state["answer"]
    assert request.request_number in state["answer"]

    # The number alone is not a cancel intent — the employee must name the
    # request in a request context (matching the real deterministic
    # interception's _has_request_context check).
    state = await harness.turn(f"cancel request {request.request_number}")
    assert f"Cancel leave request {request.request_number}" in state["answer"]

    state = await harness.turn("yes")
    assert "cancelled" in state["answer"].lower()
    db.expire_all()
    assert svc.get_my_request_by_reference(employee_context, request.request_number).status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_non_pending_rejected(db, manager_context, employee_context):
    """An already-decided request is surfaced at stage time, never staged."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    svc.decide_request(manager_context, request.leave_request_id, approve=True)
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn(f"cancel request {request.request_number}")
    assert "Only pending requests can be cancelled" in state["answer"]
    assert _workflow_row(db, harness.conversation_id, employee_context) is None


@pytest.mark.asyncio
async def test_insufficient_balance_rejected_at_stage(db, manager_context, employee_context):
    """Requesting more days than the balance allows fails at stage time —
    nothing is staged and no row is created."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, default_days=Decimal(2))
    harness = LeaveChatE2E(db, employee_context)

    state = await harness.turn("i want to apply for annual leave tomorrow for 30 days")
    assert harness.provider.calls == 0
    assert "Not enough" in state["answer"]
    assert "balance" in state["answer"]
    assert _request_count(db) == 0
    # The draft is KEPT (so the employee can adjust dates) but nothing was
    # staged and no submit was executed.
    row = _workflow_row(db, harness.conversation_id, employee_context)
    assert row is not None
    assert row.pending_confirmation is None


@pytest.mark.asyncio
async def test_expired_confirmation_rejected(db, manager_context, employee_context):
    """A staged confirmation past its TTL cannot execute."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    await harness.turn("i want to apply for annual leave tomorrow")
    await harness.turn("for 3 days")
    assert _workflow_row(db, harness.conversation_id, employee_context) is not None

    # Age the staged confirmation past its TTL.
    state = harness.store.get(str(harness.conversation_id), employee_context)
    state.pending_confirmation = replace(
        state.pending_confirmation,
        expires_at=get_clock().now() - timedelta(minutes=1),
    )

    result = await harness.turn("yes")
    assert "expired" in result["answer"].lower()
    assert _request_count(db) == 0


@pytest.mark.asyncio
async def test_mismatched_confirmation_blocked(db, manager_context, employee_context):
    """A model confirming with wrong args cannot execute — the gate blocks it."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context, provider=WrongArgsProvider())

    await harness.turn("i want to apply for annual leave tomorrow")
    await harness.turn("for 3 days")
    assert _workflow_row(db, harness.conversation_id, employee_context) is not None

    result = await harness.turn("yes")
    assert "don't have that staged" in result["answer"]
    assert _request_count(db) == 0


@pytest.mark.asyncio
async def test_leave_scoped_recap_answers_from_thread(db, manager_context, employee_context):
    """'what leave did i apply above' is answered from the thread's own
    history + workflow state, never from the DB."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    await harness.turn("i want to apply for annual leave tomorrow")
    state = await harness.turn("what leave did i apply above")

    assert harness.provider.calls == 0  # recap is deterministic
    assert "Here's what we've discussed" in state["answer"]
    assert "i want to apply for annual leave tomorrow" in state["answer"]
    assert "In progress" in state["answer"]


@pytest.mark.asyncio
async def test_draft_cancel_words_drop_draft(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    await harness.turn("i want to apply for annual leave tomorrow")
    assert _workflow_row(db, harness.conversation_id, employee_context) is not None

    state = await harness.turn("never mind, forget it")
    assert harness.provider.calls == 0
    assert "dropped that draft" in state["answer"]
    db.expire_all()
    assert _workflow_row(db, harness.conversation_id, employee_context) is None


# --- HR administrator -------------------------------------------------------


@pytest.mark.asyncio
async def test_hr_approve_roundtrip(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn(f"approve request {request.request_number}")
    assert harness.provider.calls == 0
    assert f"Approve leave request {request.request_number}" in state["answer"]

    state = await harness.turn("yes")
    assert harness.provider.calls == 1
    assert "approved" in state["answer"].lower()
    db.expire_all()
    assert svc.get_request_by_number(manager_context, request.request_number).status == "APPROVED"


@pytest.mark.asyncio
async def test_hr_reject_roundtrip(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn(f"reject request {request.request_number}")
    assert f"Reject leave request {request.request_number}" in state["answer"]

    state = await harness.turn("yes")
    assert "rejected" in state["answer"].lower()
    db.expire_all()
    assert svc.get_request_by_number(manager_context, request.request_number).status == "REJECTED"


@pytest.mark.asyncio
async def test_hr_cannot_cancel(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn(f"cancel request {request.request_number}")
    assert harness.provider.calls == 0
    assert "employee's own action" in state["answer"]
    assert _workflow_row(db, harness.conversation_id, manager_context) is None


@pytest.mark.asyncio
async def test_hr_pending_list_deterministic(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn("show me the pending leave requests")
    assert harness.provider.calls == 0
    assert request.request_number in state["answer"]
    assert "Reply with the request number" in state["answer"]


@pytest.mark.asyncio
async def test_hr_cannot_apply_for_leave(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn("i want to apply for annual leave tomorrow")
    assert harness.provider.calls == 0
    assert "can't apply" in state["answer"]
    assert _request_count(db) == 0


@pytest.mark.asyncio
async def test_hr_employee_balance_tool(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, manager_context)

    state = await harness.turn("what's the balance for EMP-TEST-001")
    assert harness.provider.calls == 1
    assert "Annual Leave" in state["answer"]
    assert "20.0 of 20.0 days remaining" in state["answer"]


@pytest.mark.asyncio
async def test_hr_list_all_requests_deterministic(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, manager_context, provider=_ManagerListProvider())

    state = await harness.turn("show me all leave requests")
    # The manager list is answered deterministically — the model is never
    # consulted, so it cannot mis-route to a self-service tool.
    assert harness.provider.calls == 0
    assert request.request_number in state["answer"]
    assert "PENDING" in state["answer"]


class _ManagerListProvider(ScriptedChatProvider):
    """Model that calls the HR list_leave_requests tool."""

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return {"reply": "Let me pull that up.", "action": "call_tool", "tool": "list_leave_requests", "args": {}}


# --- role isolation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_employee_cannot_use_hr_tools(db, manager_context, employee_context):
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    harness = LeaveChatE2E(db, employee_context, provider=_ManagerListProvider())

    state = await harness.turn("show me someone else's balance")
    assert state["answer"] == "Only HR administrators can review or act on another employee's leave."

    # A manager WRITE call has no staged confirmation to match.
    harness2 = LeaveChatE2E(db, employee_context, provider=ScriptedChatProvider())
    state = await harness2.turn("yes")
    assert harness2.provider.calls == 1
    assert "How can I help" in state["answer"] or "staged" in state["answer"]


@pytest.mark.asyncio
async def test_candidate_blocked_from_all_leave_tools(db, candidate_context):
    harness = LeaveChatE2E(db, candidate_context)

    state = await harness.turn("how much leave do i have")
    assert "only available to employees" in state["answer"]


# --- supervisor routing (non-leave routes) ----------------------------------


@pytest.mark.asyncio
async def test_knowledge_question_routes_to_knowledge():
    graph = build_supervisor_graph(
        llm=FakeLLM("knowledge"), knowledge_service=FakeKnowledgeService(make_result())
    )
    state = await graph.ainvoke({"messages": [], "current_query": "What is the annual leave policy?"})
    assert state["agent"] == "knowledge"
    assert state["answer"] == "A grounded answer. [1]"
    assert len(state["citations"]) == 1
    assert state["citations"][0].document_title == "Leave Policy"


@pytest.mark.asyncio
async def test_recruitment_question_routes_to_recruitment():
    graph = build_supervisor_graph(
        llm=FakeLLM("recruitment"), knowledge_service=FakeKnowledgeService(make_result())
    )
    state = await graph.ainvoke({"messages": [], "current_query": "how do i apply for a job?"})
    assert state["agent"] == "recruitment"
    assert "Careers" in state["answer"]


@pytest.mark.asyncio
async def test_ambiguous_message_routes_to_clarify():
    graph = build_supervisor_graph(
        llm=FakeLLM("clarify"), knowledge_service=FakeKnowledgeService(make_result())
    )
    state = await graph.ainvoke({"messages": [], "current_query": "hi"})
    assert state["agent"] == "clarify"
    assert "Could you clarify" in state["answer"]


@pytest.mark.asyncio
async def test_no_llm_heuristic_routing():
    graph = build_supervisor_graph(llm=None, knowledge_service=FakeKnowledgeService(make_result()))
    state = await graph.ainvoke({"messages": [], "current_query": "what is annual leave"})
    assert state["agent"] == "leave"
    state = await graph.ainvoke({"messages": [], "current_query": "what is the dress code"})
    assert state["agent"] == "knowledge"


@pytest.mark.asyncio
async def test_generic_recap_routes_to_recap_node():
    graph = build_supervisor_graph(
        llm=FakeLLM("We discussed the annual leave policy and your leave balance."),
        knowledge_service=FakeKnowledgeService(make_result()),
    )
    history = [
        HumanMessage(content="what is the annual leave policy?"),
        AIMessage(content="Annual leave accrues at 1.5 days per month. [1]"),
    ]
    state = await graph.ainvoke({"messages": history, "current_query": "what is this chat about?"})
    assert state["agent"] == "recap"
    assert state["answer"] == "We discussed the annual leave policy and your leave balance."


@pytest.mark.asyncio
async def test_history_is_preserved_across_turns(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    harness = LeaveChatE2E(db, employee_context)

    await harness.turn("i want to apply for annual leave tomorrow")
    state = await harness.turn("for 3 days")
    assert "Submit an Annual Leave request" in state["answer"]
    # The graph state carried both prior turns plus the new reply.
    assert len(harness.history) == 4


# --- workflow durability ----------------------------------------------------


@pytest.mark.asyncio
async def test_draft_survives_store_restart_and_completes(db, manager_context, employee_context):
    """A cache miss (simulated restart) restores the draft from the durable
    row; the follow-up end date resolves against the RESTORED start, and the
    confirmation executes after another restart."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, employee_context)
    db.commit()

    first = LeaveChatE2E(db, employee_context, conversation_id=conversation_id)
    await first.turn("i want to apply for annual leave tomorrow")
    assert _workflow_row(db, conversation_id, employee_context) is not None

    # Simulated restart: a brand-new store, same conversation.
    second = LeaveChatE2E(db, employee_context, conversation_id=conversation_id)
    state = await second.turn("for 3 days")
    assert second.provider.calls == 0  # resolved against the restored draft
    assert "Submit an Annual Leave request" in state["answer"]

    third = LeaveChatE2E(db, employee_context, conversation_id=conversation_id)
    state = await third.turn("yes")
    assert third.provider.calls == 1
    assert "submitted" in state["answer"].lower()
    assert _request_count(db) == 1

    # The workflow is marked terminal and never restored again.
    db.expire_all()
    terminal = db.scalar(
        select(ConversationWorkflowState).where(
            ConversationWorkflowState.conversation_id == conversation_id
        )
    )
    assert terminal.status == STATUS_COMPLETED
    assert _workflow_row(db, conversation_id, employee_context) is None


@pytest.mark.asyncio
async def test_completed_workflow_starts_fresh(db, manager_context, employee_context):
    """After a completed submit, a fresh session for the same conversation
    starts from scratch — the completed workflow is never resurrected."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, employee_context)
    db.commit()

    first = LeaveChatE2E(db, employee_context, conversation_id=conversation_id)
    await first.turn("i want to apply for annual leave tomorrow")
    await first.turn("for 3 days")
    await first.turn("yes")
    assert _request_count(db) == 1

    fresh = LeaveChatE2E(db, employee_context, conversation_id=conversation_id)
    state = await fresh.turn("hello again")
    assert fresh.provider.calls == 1
    assert state["answer"] == "How can I help with your leave?"
    state = fresh.store.get(str(conversation_id), employee_context)
    assert state.draft is None
    assert state.pending_confirmation is None
