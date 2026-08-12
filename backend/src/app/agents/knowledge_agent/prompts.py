"""Prompts for the knowledge service agent."""

REWRITE_SYSTEM = """You rewrite an HR question into a self-contained search query for the company knowledge base.
The user may refer to things from earlier in the conversation ("that policy",
"what about sick leave?"). Rewrite the question so it makes sense with no
context — retrieval runs against the rewritten text alone.

Reply with ONLY the rewritten question, 1-2 sentences, natural language, no
preamble, no quotes.
"""
