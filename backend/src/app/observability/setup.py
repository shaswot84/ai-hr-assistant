"""OpenTelemetry, OpenInference, and Phoenix initialization.

Configures the OpenTelemetry TracerProvider, exports spans via OTLP HTTP to
the Arize Phoenix collector, and activates auto-instrumentors (FastAPI and
LangChain / LangGraph).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config.settings import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_PROVIDER: TracerProvider | None = None
_LANGCHAIN_INSTRUMENTOR: LangChainInstrumentor | None = None


def init_observability(app: FastAPI | None = None) -> TracerProvider | None:
    """Initialize OpenTelemetry tracer provider, OTLP exporter, and auto-instrumentations.

    Safe and non-blocking: if disabled or Phoenix is offline, application execution
    proceeds without interruption.
    """
    global _PROVIDER, _LANGCHAIN_INSTRUMENTOR

    settings = get_settings().observability
    if not settings.enabled:
        logger.info("Observability is disabled via settings (OTEL_ENABLED=false).")
        return None

    try:
        # Build OpenTelemetry Resource with service and OpenInference project metadata
        resource_attributes: dict[str, Any] = {
            "service.name": settings.service_name,
            "deployment.environment": get_settings().app_env,
            "openinference.project.name": settings.project_name,
            "service.version": "0.1.0",
        }
        resource = Resource.create(resource_attributes)

        # Set up TracerProvider
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        _PROVIDER = provider

        # Configure OTLP HTTP Span Exporter targeting Phoenix collector
        endpoint = settings.exporter_otlp_endpoint
        exporter = OTLPSpanExporter(endpoint=endpoint)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        # Auto-instrument LangChain and LangGraph runnables / state graphs
        if settings.instrument_langchain:
            try:
                _LANGCHAIN_INSTRUMENTOR = LangChainInstrumentor()
                _LANGCHAIN_INSTRUMENTOR.instrument(tracer_provider=provider)
                logger.info("OpenInference LangChain instrumentor initialized.")
            except Exception as err:  # noqa: BLE001
                logger.warning("Failed to initialize LangChain instrumentor: %s", err)

        # Auto-instrument FastAPI app endpoints
        if app is not None and settings.instrument_fastapi:
            try:
                FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
                logger.info("FastAPI OpenTelemetry instrumentor initialized.")
            except Exception as err:  # noqa: BLE001
                logger.warning("Failed to initialize FastAPI instrumentor: %s", err)

        logger.info(
            "Observability initialized successfully. Exporting traces to %s (project: %s).",
            endpoint,
            settings.project_name,
        )
        return provider

    except Exception as err:
        logger.warning("Failed to initialize OpenTelemetry observability: %s", err, exc_info=True)
        return None


def shutdown_observability() -> None:
    """Flush pending spans and cleanly shut down the TracerProvider."""
    global _PROVIDER, _LANGCHAIN_INSTRUMENTOR

    if _LANGCHAIN_INSTRUMENTOR is not None:
        try:
            _LANGCHAIN_INSTRUMENTOR.uninstrument()
        except Exception as err:  # noqa: BLE001
            logger.debug("LangChain uninstrument: %s", err)
        _LANGCHAIN_INSTRUMENTOR = None

    if _PROVIDER is not None:
        try:
            _PROVIDER.force_flush()
            _PROVIDER.shutdown()
        except Exception as err:  # noqa: BLE001
            logger.warning("Error shutting down TracerProvider: %s", err)
        _PROVIDER = None
