"""Unit tests for the output-safety factory wiring."""

from app.config.settings import AppSettings, OutputSafetySettings
from app.safety.factory import build_output_guard
from app.safety.output.guards.citations import CitationCoverageCheck
from app.safety.output.guards.evidence import EvidenceGate
from app.safety.output.guards.pii import PIIRedactionCheck
from app.safety.output.guards.topic import SensitiveTopicGate
from app.safety.output.judge.ollama import OllamaClaimVerifier
from app.safety.output.judge.passthrough import PassThroughClaimVerifier
from app.safety.pipeline import OutputSafetyPipeline


def make_settings(**overrides) -> AppSettings:
    return AppSettings(
        debug=False,
        output_safety=OutputSafetySettings(**overrides),
    )


def test_default_pipeline_has_all_deterministic_guards():
    pipeline = build_output_guard(make_settings())

    guard_names = [type(check).__name__ for check in pipeline._checks]
    assert guard_names == [
        EvidenceGate.__name__,
        CitationCoverageCheck.__name__,
        SensitiveTopicGate.__name__,
        PIIRedactionCheck.__name__,
    ]
    assert isinstance(pipeline._verifier, PassThroughClaimVerifier)


def test_judge_enabled_builds_ollama_verifier():
    pipeline = build_output_guard(make_settings(judge_enabled=True))

    assert isinstance(pipeline._verifier, OllamaClaimVerifier)
    assert pipeline._verifier.model == "llama3.2"


def test_disabled_omits_guards_and_verifier():
    pipeline = build_output_guard(make_settings(enabled=False))

    assert pipeline._checks == []
    assert isinstance(pipeline._verifier, PassThroughClaimVerifier)


def test_optional_guards_respect_settings():
    pipeline = build_output_guard(
        make_settings(require_citation=False, redact_pii=False)
    )

    guard_names = [type(check).__name__ for check in pipeline._checks]
    assert guard_names == [EvidenceGate.__name__, SensitiveTopicGate.__name__]


def test_sensitive_topics_flow_into_gate():
    pipeline = build_output_guard(make_settings(sensitive_topics=["LEGAL_ADVICE"]))

    topic_gate = next(
        c for c in pipeline._checks if isinstance(c, SensitiveTopicGate)
    )
    assert topic_gate._topics == {"LEGAL_ADVICE"}


def test_returns_pipeline_interface():
    assert isinstance(build_output_guard(make_settings()), OutputSafetyPipeline)
