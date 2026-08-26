"""Observability module for OpenTelemetry, OpenInference, and Arize Phoenix."""

from app.observability.setup import init_observability, shutdown_observability
from app.observability.tracing import (
    async_trace_span,
    get_tracer,
    set_embedding_details,
    set_llm_token_counts,
    set_reranker_details,
    set_retrieval_documents,
    trace_agent_turn,
    trace_chat_turn,
    trace_llm_call,
    trace_span,
    trace_tool_call,
)

__all__ = [
    "async_trace_span",
    "get_tracer",
    "init_observability",
    "set_embedding_details",
    "set_llm_token_counts",
    "set_reranker_details",
    "set_retrieval_documents",
    "shutdown_observability",
    "trace_agent_turn",
    "trace_chat_turn",
    "trace_llm_call",
    "trace_span",
    "trace_tool_call",
]

