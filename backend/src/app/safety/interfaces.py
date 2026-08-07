"""Output Safety interfaces.

Guards are composable checks; the pipeline reduces their findings into a
single verdict. The claim verifier is an optional LLM-as-judge and is always
replaceable (the default is a no-op pass-through).
"""

import abc

from app.safety.contracts import GuardFinding, GuardResult, OutputContext


class GuardCheck(abc.ABC):
    """A single, composable output-safety check."""

    name: str = ""

    @abc.abstractmethod
    async def check(self, context: OutputContext) -> list[GuardFinding]:
        """Return the findings this guard produces for the response."""
        raise NotImplementedError


class ClaimVerifier(abc.ABC):
    """Optional LLM-as-judge that verifies the response against evidence.

    ``verify`` returns a finding only when the response is unsupported; a
    supported (or unverifiable) response yields no finding.
    """

    model: str = ""

    @abc.abstractmethod
    async def verify(self, context: OutputContext) -> GuardFinding | None:
        """Return a finding when the response is not supported, else None."""
        raise NotImplementedError


class ResponseGuard(abc.ABC):
    """The full output-safety pipeline applied to a response."""

    @abc.abstractmethod
    async def guard(self, context: OutputContext) -> GuardResult:
        raise NotImplementedError
