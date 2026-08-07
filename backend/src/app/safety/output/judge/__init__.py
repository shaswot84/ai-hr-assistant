"""LLM-as-judge verifiers.

The claim verifier is optional: the default is a no-op pass-through, and an
Ollama-backed verifier is wired when ``OUTPUT_SAFETY_JUDGE_ENABLED=true``.
"""
