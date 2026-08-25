"""OpenTelemetry and OpenInference semantic tracing helpers.

Provides context managers and utility functions for instrumenting RAG pipelines,
Multi-Agent interactions, tool calls, and LLM completions according to
OpenInference and Arize Phoenix conventions.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any

from openinference.semconv.trace import (
    DocumentAttributes,
    MessageAttributes,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

if TYPE_CHECKING:
    from app.knowledge.contracts import RetrievedChunk

_TRACER_NAME = "ai-hr-assistant"


def get_tracer(name: str = _TRACER_NAME) -> trace.Tracer:
    """Return an OpenTelemetry Tracer instance."""
    return trace.get_tracer(name)


@contextmanager
def trace_span(
    name: str,
    span_kind: str | OpenInferenceSpanKindValues | None = OpenInferenceSpanKindValues.CHAIN,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Synchronous context manager creating a traced span with OpenInference conventions."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, set_status_on_exception=True) as span:
        if span_kind is not None:
            kind_val = span_kind.value if isinstance(span_kind, OpenInferenceSpanKindValues) else str(span_kind)
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind_val)

        if attributes:
            for key, val in attributes.items():
                if val is not None:
                    if isinstance(val, (dict, list)):
                        try:
                            span.set_attribute(key, json.dumps(val, default=str))
                        except Exception:  # noqa: BLE001
                            span.set_attribute(key, str(val))
                    else:
                        span.set_attribute(key, val)

        try:
            yield span
            if span.is_recording() and span.status.status_code == StatusCode.UNSET:
                span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            if span.is_recording():
                span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            raise


@asynccontextmanager
async def async_trace_span(
    name: str,
    span_kind: str | OpenInferenceSpanKindValues | None = OpenInferenceSpanKindValues.CHAIN,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[Span]:
    """Asynchronous context manager creating a traced span with OpenInference conventions."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, set_status_on_exception=True) as span:
        if span_kind is not None:
            kind_val = span_kind.value if isinstance(span_kind, OpenInferenceSpanKindValues) else str(span_kind)
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind_val)

        if attributes:
            for key, val in attributes.items():
                if val is not None:
                    if isinstance(val, (dict, list)):
                        try:
                            span.set_attribute(key, json.dumps(val, default=str))
                        except Exception:  # noqa: BLE001
                            span.set_attribute(key, str(val))
                    else:
                        span.set_attribute(key, val)

        try:
            yield span
            if span.is_recording() and span.status.status_code == StatusCode.UNSET:
                span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            if span.is_recording():
                span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            raise


def set_retrieval_documents(
    span: Span,
    chunks: list[RetrievedChunk],
    *,
    max_documents: int = 50,
) -> None:
    """Populate OpenInference RETRIEVAL_DOCUMENTS on a retriever span for Phoenix RAG visualization."""
    if not span.is_recording():
        return

    doc_prefix = SpanAttributes.RETRIEVAL_DOCUMENTS
    span.set_attribute("rag.document_count", len(chunks))

    for idx, chunk in enumerate(chunks[:max_documents]):
        item_prefix = f"{doc_prefix}.{idx}"

        span.set_attribute(f"{item_prefix}.{DocumentAttributes.DOCUMENT_ID}", str(chunk.chunk_id))

        # Full rendered content with parent context when present
        content = chunk.text
        if chunk.parent_context:
            content = f"[Context: {chunk.section_title or ''}]\n{chunk.parent_context}\n\n{chunk.text}"
        span.set_attribute(f"{item_prefix}.{DocumentAttributes.DOCUMENT_CONTENT}", content)

        if chunk.retrieval_score is not None:
            span.set_attribute(
                f"{item_prefix}.{DocumentAttributes.DOCUMENT_SCORE}",
                float(chunk.retrieval_score),
            )

        metadata = {
            "document_id": str(chunk.document_id),
            "document_version_id": str(chunk.document_version_id),
            "document_title": chunk.document_title,
            "version_number": chunk.version_number,
            "category": chunk.category.value if hasattr(chunk.category, "value") else str(chunk.category),
            "page": chunk.page,
            "section_title": chunk.section_title,
            "has_parent_context": bool(chunk.parent_context),
            "parent_context_length": len(chunk.parent_context) if chunk.parent_context else 0,
        }
        span.set_attribute(
            f"{item_prefix}.{DocumentAttributes.DOCUMENT_METADATA}",
            json.dumps(metadata),
        )


@asynccontextmanager
async def trace_agent_turn(
    agent_name: str,
    query: str,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> AsyncIterator[Span]:
    """Trace an Agent turn with OpenInference AGENT semantic conventions."""
    attributes: dict[str, Any] = {
        SpanAttributes.AGENT_NAME: agent_name,
        SpanAttributes.INPUT_VALUE: query,
    }
    if conversation_id:
        attributes[SpanAttributes.SESSION_ID] = str(conversation_id)
    if user_id:
        attributes[SpanAttributes.USER_ID] = str(user_id)

    async with async_trace_span(
        f"agent.{agent_name}",
        span_kind=OpenInferenceSpanKindValues.AGENT,
        attributes=attributes,
    ) as span:
        yield span


@asynccontextmanager
async def trace_tool_call(
    tool_name: str,
    parameters: dict[str, Any] | None = None,
    description: str | None = None,
) -> AsyncIterator[Span]:
    """Trace a Tool call execution with OpenInference TOOL semantic conventions."""
    attributes: dict[str, Any] = {
        SpanAttributes.TOOL_NAME: tool_name,
    }
    if parameters:
        try:
            attributes[SpanAttributes.TOOL_PARAMETERS] = json.dumps(parameters, default=str)
        except Exception:  # noqa: BLE001
            attributes[SpanAttributes.TOOL_PARAMETERS] = str(parameters)
    if description:
        attributes[SpanAttributes.TOOL_DESCRIPTION] = description

    async with async_trace_span(
        f"tool.{tool_name}",
        span_kind=OpenInferenceSpanKindValues.TOOL,
        attributes=attributes,
    ) as span:
        yield span


@asynccontextmanager
async def trace_llm_call(
    model_name: str,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    invocation_parameters: dict[str, Any] | None = None,
) -> AsyncIterator[Span]:
    """Trace an LLM call with OpenInference LLM semantic conventions."""
    attributes: dict[str, Any] = {
        SpanAttributes.LLM_MODEL_NAME: model_name,
        SpanAttributes.LLM_SYSTEM: "ollama",
    }
    if invocation_parameters:
        try:
            attributes[SpanAttributes.LLM_INVOCATION_PARAMETERS] = json.dumps(
                invocation_parameters, default=str
            )
        except Exception:  # noqa: BLE001
            attributes[SpanAttributes.LLM_INVOCATION_PARAMETERS] = str(invocation_parameters)

    # Record input messages in OpenInference format
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})

    if messages:
        msg_prefix = SpanAttributes.LLM_INPUT_MESSAGES
        for i, msg in enumerate(messages):
            attributes[f"{msg_prefix}.{i}.{MessageAttributes.MESSAGE_ROLE}"] = msg["role"]
            attributes[f"{msg_prefix}.{i}.{MessageAttributes.MESSAGE_CONTENT}"] = msg["content"]
        attributes[SpanAttributes.INPUT_VALUE] = user_prompt or system_prompt or ""

    async with async_trace_span(
        f"llm.{model_name}",
        span_kind=OpenInferenceSpanKindValues.LLM,
        attributes=attributes,
    ) as span:
        yield span


def set_llm_token_counts(
    span: Span,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    """Populate OpenInference token counts on an LLM span for Phoenix metrics."""
    if not span.is_recording():
        return
    if prompt_tokens is not None:
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_PROMPT, int(prompt_tokens))
    if completion_tokens is not None:
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, int(completion_tokens))
    if total_tokens is not None:
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_TOTAL, int(total_tokens))
    elif prompt_tokens is not None and completion_tokens is not None:
        span.set_attribute(
            SpanAttributes.LLM_TOKEN_COUNT_TOTAL,
            int(prompt_tokens) + int(completion_tokens),
        )


@asynccontextmanager
async def trace_chat_turn(
    query: str,
    conversation_id: str | None = None,
    user_id: str | None = None,
    actor_role: str | None = None,
) -> AsyncIterator[Span]:
    """Trace a top-level Chat turn encompassing routing, sub-agents, tools, and output generation."""
    attributes: dict[str, Any] = {
        SpanAttributes.INPUT_VALUE: query,
    }
    if conversation_id:
        attributes[SpanAttributes.SESSION_ID] = str(conversation_id)
    if user_id:
        attributes[SpanAttributes.USER_ID] = str(user_id)
    if actor_role:
        attributes["actor.role"] = actor_role

    async with async_trace_span(
        "chat.turn",
        span_kind=OpenInferenceSpanKindValues.CHAIN,
        attributes=attributes,
    ) as span:
        yield span

