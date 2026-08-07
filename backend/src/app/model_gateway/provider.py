from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ChatProviderError(Exception):
    """Raised when a chat provider cannot fulfil a completion request."""


class ChatProvider(ABC):
    """Swappable chat-inference seam (Model Gateway).

    Recruitment scoring talks to this interface only. Ollama hosted API is
    the MVP provider; a deterministic fallback covers no-key dev runs.
    """

    @abstractmethod
    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Return a parsed JSON object from the model. Raises ChatProviderError on failure."""
