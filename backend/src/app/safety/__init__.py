"""Output Safety layer.

Guards the final agent response before it is served: evidence gate, citation
coverage, PII redaction, sensitive-topic gating, and (optionally) an
LLM-as-judge claim verifier.
"""

from app.safety.contracts import (
    FindingSeverity,
    GuardFinding,
    GuardResult,
    GuardVerdict,
    OutputContext,
)
from app.safety.factory import build_output_guard
from app.safety.interfaces import ClaimVerifier, GuardCheck, ResponseGuard
from app.safety.pipeline import OutputSafetyPipeline

__all__ = [
    "ClaimVerifier",
    "FindingSeverity",
    "GuardCheck",
    "GuardFinding",
    "GuardResult",
    "GuardVerdict",
    "OutputContext",
    "OutputSafetyPipeline",
    "ResponseGuard",
    "build_output_guard",
]
