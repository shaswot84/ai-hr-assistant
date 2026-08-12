"""Request/response contracts for the chat API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """One turn of the conversation: a message, optionally continuing a thread."""

    # Omit to start a new conversation.
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)


class CitationOut(BaseModel):
    """A source document cited in an assistant reply."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    version_number: int
    document_title: str
    category: str
    page: int | None = None
    section_title: str | None = None


class ChatResponse(BaseModel):
    """The assistant's reply to one chat turn."""

    conversation_id: uuid.UUID
    message: str
    citations: list[CitationOut] = Field(default_factory=list)
    confidence: float = 0.0
    low_confidence: bool = False
    agent: str  # knowledge | leave | recruitment | clarify


class ConversationSummary(BaseModel):
    """A conversation as shown in the history list."""

    conversation_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    """One stored message in a conversation transcript."""

    message_id: uuid.UUID
    role: str  # user | assistant | system
    content: str
    citations: list[dict] | None
    meta: dict | None
    created_at: datetime
