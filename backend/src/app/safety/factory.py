"""Wiring from settings to the Output Safety pipeline.

The deployment choice (deterministic guards only vs. + LLM-as-judge) is
decided here, so callers depend only on the ``ResponseGuard`` interface.
"""

from app.config.settings import AppSettings, get_settings
from app.safety.interfaces import ClaimVerifier, GuardCheck, ResponseGuard
from app.safety.output.guards.citations import CitationCoverageCheck
from app.safety.output.guards.evidence import EvidenceGate
from app.safety.output.guards.pii import PIIRedactionCheck
from app.safety.output.guards.topic import SensitiveTopicGate
from app.safety.output.judge.ollama import OllamaClaimVerifier
from app.safety.output.judge.passthrough import PassThroughClaimVerifier
from app.safety.pipeline import OutputSafetyPipeline


def build_output_guard(settings: AppSettings | None = None) -> ResponseGuard:
    """Build the output-safety pipeline from settings."""
    settings = settings or get_settings()
    safety = settings.output_safety

    checks: list[GuardCheck] = []
    if safety.enabled:
        checks.append(EvidenceGate(settings.retrieval))
        if safety.require_citation:
            checks.append(CitationCoverageCheck())
        checks.append(SensitiveTopicGate(safety.sensitive_topics))
        if safety.redact_pii:
            checks.append(PIIRedactionCheck(redaction_token=safety.redaction_token))

    return OutputSafetyPipeline(checks=checks, verifier=_build_verifier(settings))


def _build_verifier(settings: AppSettings) -> ClaimVerifier:
    safety = settings.output_safety
    if not safety.enabled or not safety.judge_enabled:
        return PassThroughClaimVerifier()
    return OllamaClaimVerifier(
        base_url=settings.model_gateway.url,
        model=safety.judge_model,
        timeout_seconds=safety.judge_timeout_seconds,
    )
