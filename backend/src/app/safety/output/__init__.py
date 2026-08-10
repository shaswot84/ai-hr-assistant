"""Output Safety stage.

Guards the final agent response before it is served: evidence gate, citation
coverage, PII redaction, sensitive-topic gating, and (optionally) an
LLM-as-judge claim verifier. The shared verdict/finding types and the
``GuardCheck`` / ``ClaimVerifier`` interfaces live in the parent
``app.safety`` package because the Input and Retrieval safety stages reuse
them.
"""
