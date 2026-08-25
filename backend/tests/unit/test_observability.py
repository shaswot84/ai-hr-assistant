"""Unit tests for OpenTelemetry, OpenInference, and Phoenix observability integration."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from openinference.semconv.trace import (
    DocumentAttributes,
    MessageAttributes,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.config.settings import ObservabilitySettings
from app.knowledge.contracts import RetrievedChunk
from app.knowledge.models import DocumentCategory
from app.observability import (
    async_trace_span,
    init_observability,
    set_llm_token_counts,
    set_retrieval_documents,
    shutdown_observability,
    trace_agent_turn,
    trace_chat_turn,
    trace_llm_call,
    trace_span,
    trace_tool_call,
)


@pytest.fixture()
def memory_exporter():
    """Set up an in-memory span exporter for testing trace emission."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter, provider


def test_init_observability_disabled(monkeypatch):
    """When OTEL_ENABLED=false, init_observability should return None."""
    with patch("app.observability.setup.get_settings") as mock_settings:
        mock_settings.return_value.observability = ObservabilitySettings(enabled=False)
        provider = init_observability()
        assert provider is None


def test_init_observability_enabled(monkeypatch):
    """When enabled, init_observability should initialize TracerProvider and instrumentations."""
    with patch("app.observability.setup.get_settings") as mock_settings:
        mock_settings.return_value.observability = ObservabilitySettings(
            enabled=True,
            service_name="test-service",
            exporter_otlp_endpoint="http://localhost:6006/v1/traces",
            project_name="test-project",
            instrument_fastapi=False,
            instrument_langchain=False,
        )
        mock_settings.return_value.app_env = "test"
        provider = init_observability()
        assert provider is not None
        shutdown_observability()


def test_trace_span_sync(memory_exporter):
    exporter, provider = memory_exporter
    with (
        patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")),
        trace_span(
            "test.sync_span",
            span_kind=OpenInferenceSpanKindValues.CHAIN,
            attributes={"custom.key": "custom.value"},
        ) as span,
    ):
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, "result")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "test.sync_span"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "CHAIN"
    assert s.attributes["custom.key"] == "custom.value"
    assert s.attributes[SpanAttributes.OUTPUT_VALUE] == "result"


@pytest.mark.asyncio
async def test_trace_span_async(memory_exporter):
    exporter, provider = memory_exporter
    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        async with async_trace_span(
            "test.async_span",
            span_kind=OpenInferenceSpanKindValues.AGENT,
            attributes={"agent.step": 1},
        ) as span:
            span.set_attribute("agent.done", True)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "test.async_span"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "AGENT"
    assert s.attributes["agent.step"] == 1
    assert s.attributes["agent.done"] is True


@pytest.mark.asyncio
async def test_trace_span_error_recording(memory_exporter):
    exporter, provider = memory_exporter
    with (
        patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")),
        pytest.raises(ValueError, match="test error"),
    ):
        async with async_trace_span("test.error_span"):
            raise ValueError("test error")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.status.status_code.name == "ERROR"
    assert len(s.events) == 1
    assert s.events[0].name == "exception"


def test_set_retrieval_documents_with_parent_expansion(memory_exporter):
    exporter, provider = memory_exporter
    chunk_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    version_id = uuid.uuid4()

    chunk = RetrievedChunk(
        chunk_id=chunk_id,
        document_id=doc_id,
        document_version_id=version_id,
        version_number=1,
        document_title="Employee Handbook",
        category=DocumentCategory.POLICY,
        mime_type="application/pdf",
        page=5,
        section_title="Sick Leave",
        text="Employees receive 10 paid sick days per year.",
        parent_context="Section 4: Leave Types and Benefits\nEmployees receive 10 paid sick days per year.",
        retrieval_score=0.92,
        provenance={"rank": 1},
    )

    with (
        patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")),
        trace_span("rag.retrieve", span_kind=OpenInferenceSpanKindValues.RETRIEVER) as span,
    ):
        set_retrieval_documents(span, [chunk])

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "RETRIEVER"
    assert s.attributes["rag.document_count"] == 1

    doc_prefix = f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.0"
    assert s.attributes[f"{doc_prefix}.{DocumentAttributes.DOCUMENT_ID}"] == str(chunk_id)
    assert "[Context: Sick Leave]" in s.attributes[f"{doc_prefix}.{DocumentAttributes.DOCUMENT_CONTENT}"]
    assert s.attributes[f"{doc_prefix}.{DocumentAttributes.DOCUMENT_SCORE}"] == 0.92

    meta = json.loads(s.attributes[f"{doc_prefix}.{DocumentAttributes.DOCUMENT_METADATA}"])
    assert meta["document_title"] == "Employee Handbook"
    assert meta["has_parent_context"] is True
    assert meta["section_title"] == "Sick Leave"
    assert meta["page"] == 5


@pytest.mark.asyncio
async def test_trace_agent_turn(memory_exporter):
    exporter, provider = memory_exporter
    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        async with trace_agent_turn(
            "leave",
            query="how many vacation days do I have?",
            conversation_id="conv-123",
            user_id="user-456",
        ) as span:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, "You have 15 days.")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "agent.leave"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "AGENT"
    assert s.attributes[SpanAttributes.AGENT_NAME] == "leave"
    assert s.attributes[SpanAttributes.INPUT_VALUE] == "how many vacation days do I have?"
    assert s.attributes[SpanAttributes.SESSION_ID] == "conv-123"
    assert s.attributes[SpanAttributes.USER_ID] == "user-456"
    assert s.attributes[SpanAttributes.OUTPUT_VALUE] == "You have 15 days."


@pytest.mark.asyncio
async def test_trace_tool_call(memory_exporter):
    exporter, provider = memory_exporter
    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        async with trace_tool_call(
            "get_leave_balance",
            parameters={"leave_type": "Annual Leave"},
            description="Fetch remaining balance",
        ) as span:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, json.dumps({"remaining_days": 12}))

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "tool.get_leave_balance"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "TOOL"
    assert s.attributes[SpanAttributes.TOOL_NAME] == "get_leave_balance"
    assert json.loads(s.attributes[SpanAttributes.TOOL_PARAMETERS]) == {"leave_type": "Annual Leave"}
    assert s.attributes[SpanAttributes.TOOL_DESCRIPTION] == "Fetch remaining balance"


@pytest.mark.asyncio
async def test_trace_llm_call(memory_exporter):
    exporter, provider = memory_exporter
    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        async with trace_llm_call(
            "gpt-oss:120b-cloud",
            system_prompt="You are an HR assistant.",
            user_prompt="Explain paternity leave.",
            invocation_parameters={"temperature": 0.2},
        ) as span:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, "Paternity leave is 14 days.")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "llm.gpt-oss:120b-cloud"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "LLM"
    assert s.attributes[SpanAttributes.LLM_MODEL_NAME] == "gpt-oss:120b-cloud"
    assert s.attributes[SpanAttributes.INPUT_VALUE] == "Explain paternity leave."
    assert s.attributes[f"{SpanAttributes.LLM_INPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_ROLE}"] == "system"
    assert s.attributes[f"{SpanAttributes.LLM_INPUT_MESSAGES}.1.{MessageAttributes.MESSAGE_ROLE}"] == "user"
    assert s.attributes[SpanAttributes.OUTPUT_VALUE] == "Paternity leave is 14 days."


@pytest.mark.asyncio
async def test_rag_pipeline_spans(memory_exporter):
    exporter, provider = memory_exporter
    from app.knowledge.repository import RetrievalHit
    from app.knowledge.service import KnowledgeService

    chunk_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    version_id = uuid.uuid4()

    hit = RetrievalHit(
        chunk_id=chunk_id,
        document_id=doc_id,
        document_version_id=version_id,
        version_number=1,
        document_title="Remote Work Policy",
        category=DocumentCategory.POLICY,
        mime_type="application/pdf",
        page=2,
        section_title="Eligibility",
        content="Remote work is permitted 2 days per week.",
        score=0.88,
        provenance={"rank": 1},
    )

    mock_repo = AsyncMock()
    mock_repo.has_indexed_documents.return_value = True
    mock_repo.bm25_search.return_value = [hit]
    mock_repo.vector_search.return_value = [hit]
    mock_repo.fetch_parent_context.return_value = {
        chunk_id: "Section: Remote Work Policy\nRemote work is permitted 2 days per week."
    }

    mock_embedder = AsyncMock()
    mock_embedder.embed.return_value = [[0.1] * 768]

    service = KnowledgeService(repository=mock_repo, embedder=mock_embedder)

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        result = await service.retrieve("can I work from home?")

    assert result.grounded_context != ""
    assert len(result.citations) == 1

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Verify that all RAG stages generated spans
    assert "rag.embedding" in span_names
    assert "rag.search.bm25" in span_names
    assert "rag.search.vector" in span_names
    assert "rag.ranking.rrf" in span_names
    assert "rag.reranker" in span_names
    assert "rag.parent_expansion" in span_names
    assert "rag.confidence" in span_names
    assert "rag.grounding" in span_names
    assert "rag.retrieve" in span_names

    # Verify top retriever span has OpenInference RETRIEVAL_DOCUMENTS and success status
    retriever_span = next(s for s in spans if s.name == "rag.retrieve")
    assert retriever_span.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "RETRIEVER"
    assert retriever_span.attributes[SpanAttributes.INPUT_VALUE] == "can I work from home?"
    assert f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.0.{DocumentAttributes.DOCUMENT_ID}" in retriever_span.attributes
    assert retriever_span.attributes["rag.status"] == "success"

    # Verify reranker span ranking delta
    reranker_span = next(s for s in spans if s.name == "rag.reranker")
    assert reranker_span.attributes["rag.candidates_in_count"] == 1
    assert reranker_span.attributes["rag.candidates_out_count"] == 1
    assert "rag.rerank_score_top" in reranker_span.attributes
    assert "rag.rank_shift" in reranker_span.attributes

    # Verify parent expansion metrics
    expand_span = next(s for s in spans if s.name == "rag.parent_expansion")
    assert expand_span.attributes["rag.candidates_in"] == 1
    assert expand_span.attributes["rag.expanded_chunks_count"] == 1
    assert expand_span.attributes["rag.parent_expansion_ratio"] > 1.0

    # Ensure EVERY span has a valid OpenInference kind (no "UNKNOWN" in Phoenix) and status is OK (not "UNSET")
    for s in spans:
        kind = s.attributes.get(SpanAttributes.OPENINFERENCE_SPAN_KIND)
        assert kind is not None, f"Span {s.name} is missing OpenInference span kind"
        assert kind != "UNKNOWN", f"Span {s.name} has UNKNOWN span kind"
        assert s.status.status_code == StatusCode.OK, f"Span {s.name} status is {s.status.status_code}, expected StatusCode.OK"




@pytest.mark.asyncio
async def test_rag_pipeline_refusal_spans(memory_exporter):
    exporter, provider = memory_exporter
    from app.knowledge.service import KnowledgeService

    mock_repo = AsyncMock()
    mock_repo.has_indexed_documents.return_value = False
    mock_embedder = AsyncMock()

    service = KnowledgeService(repository=mock_repo, embedder=mock_embedder)

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        result = await service.retrieve("can I work from home?")

    assert result.empty_knowledge_base is True
    spans = exporter.get_finished_spans()
    retriever_span = next(s for s in spans if s.name == "rag.retrieve")
    assert retriever_span.attributes["rag.status"] == "refused"
    assert retriever_span.attributes["rag.refusal_reason"] == "empty_kb"



@pytest.mark.asyncio
async def test_supervisor_route_intent_tracing(memory_exporter):
    exporter, provider = memory_exporter
    from app.agents.supervisor.route_intent import route_intent

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        route = await route_intent(llm=None, query="how much annual leave do I have?", history=[])

    assert route == "leave"
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "supervisor.route_intent"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "CHAIN"
    assert s.attributes["agent.route"] == "leave"
    assert s.attributes[SpanAttributes.INPUT_VALUE] == "how much annual leave do I have?"


@pytest.mark.asyncio
async def test_trace_chat_turn(memory_exporter):
    exporter, provider = memory_exporter
    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        async with trace_chat_turn(
            query="What is the bereavement leave policy?",
            conversation_id="conv-abc-123",
            user_id="usr-789",
            actor_role="EMPLOYEE",
        ) as span:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, "Bereavement leave is 5 days.")
            span.set_attribute("agent.name", "knowledge")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "chat.turn"
    assert s.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "CHAIN"
    assert s.attributes[SpanAttributes.INPUT_VALUE] == "What is the bereavement leave policy?"
    assert s.attributes[SpanAttributes.SESSION_ID] == "conv-abc-123"
    assert s.attributes[SpanAttributes.USER_ID] == "usr-789"
    assert s.attributes["actor.role"] == "EMPLOYEE"
    assert s.attributes[SpanAttributes.OUTPUT_VALUE] == "Bereavement leave is 5 days."
    assert s.attributes["agent.name"] == "knowledge"


def test_set_llm_token_counts(memory_exporter):
    exporter, provider = memory_exporter
    with (
        patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")),
        trace_span("test.llm", span_kind=OpenInferenceSpanKindValues.LLM) as span,
    ):
        set_llm_token_counts(span, prompt_tokens=42, completion_tokens=18)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] == 42
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] == 18
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] == 60


@pytest.mark.asyncio
async def test_ollama_cloud_llm_token_tracking_complete(memory_exporter):
    exporter, provider = memory_exporter
    from unittest.mock import MagicMock
    import httpx
    from app.model_gateway.llm import OllamaCloudLLM

    fake_response = {
        "model": "test-model",
        "message": {"role": "assistant", "content": "Hello world"},
        "prompt_eval_count": 25,
        "eval_count": 10,
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_post_res = MagicMock(spec=httpx.Response)
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = fake_response
    mock_post_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_post_res

    llm = OllamaCloudLLM(
        base_url="https://api.ollama.com",
        api_key="secret-key",
        model="test-model",
        client=mock_client,
    )

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        result = await llm.complete("system", "user")

    assert result == "Hello world"
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] == 25
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] == 10
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] == 35


@pytest.mark.asyncio
async def test_ollama_cloud_llm_token_tracking_stream(memory_exporter):
    exporter, provider = memory_exporter
    import httpx
    from contextlib import asynccontextmanager
    from app.model_gateway.llm import OllamaCloudLLM

    lines = [
        json.dumps({"message": {"content": "Hello"}}),
        json.dumps({"message": {"content": " world"}}),
        json.dumps({"done": True, "prompt_eval_count": 30, "eval_count": 12}),
    ]

    class FakeStreamResponse:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for line in lines:
                yield line

    @asynccontextmanager
    async def fake_stream(*args, **kwargs):
        yield FakeStreamResponse()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.stream = fake_stream

    llm = OllamaCloudLLM(
        base_url="https://api.ollama.com",
        api_key="secret-key",
        model="test-model",
        client=mock_client,
    )

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        tokens = [t async for t in llm.stream("system", "user")]

    assert "".join(tokens) == "Hello world"
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] == 30
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] == 12
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] == 42


@pytest.mark.asyncio
async def test_ollama_chat_provider_token_tracking(memory_exporter):
    exporter, provider = memory_exporter
    from unittest.mock import MagicMock
    import httpx
    from app.model_gateway.ollama import OllamaChatProvider

    fake_response = {
        "choices": [{"message": {"content": json.dumps({"status": "ok"})}}],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 20,
            "total_tokens": 70,
        },
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_post_res = MagicMock(spec=httpx.Response)
    mock_post_res.status_code = 200
    mock_post_res.json.return_value = fake_response
    mock_post_res.raise_for_status.return_value = None
    mock_client.post.return_value = mock_post_res

    chat_provider = OllamaChatProvider(
        api_base="https://api.ollama.com",
        model="test-model",
        api_key="real-key-12345",
        client=mock_client,
    )

    with patch("app.observability.tracing.get_tracer", return_value=provider.get_tracer("test")):
        res = await chat_provider.complete_json(
            system_prompt="system",
            user_prompt="user",
        )

    assert res == {"status": "ok"}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] == 50
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] == 20
    assert s.attributes[SpanAttributes.LLM_TOKEN_COUNT_TOTAL] == 70


