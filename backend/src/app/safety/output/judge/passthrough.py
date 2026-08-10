"""No-op claim verifier used when LLM-as-judge is disabled."""

from app.safety.contracts import GuardFinding, OutputContext
from app.safety.interfaces import ClaimVerifier


class PassThroughClaimVerifier(ClaimVerifier):
    """Accepts every response without consulting a model."""

    model = "passthrough"

    async def verify(self, context: OutputContext) -> GuardFinding | None:
        return None
