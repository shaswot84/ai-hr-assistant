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
    # False for non-retrieval agents (leave/recruitment/clarify/recap), whose
    # confidence is always 0.0 and has no meaning — consumers must not render
    # a confidence badge when this is False.
    confidence_applicable: bool = False
    meta: dict | None = None


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


class PublicHistoryMessage(BaseModel):
    """One prior turn sent by an anonymous client in the public chat."""

    role: str  # user | assistant
    content: str


class PublicChatRequest(BaseModel):
    """One turn of public/anonymous chat."""

    message: str = Field(min_length=1, max_length=4000)
    history: list[PublicHistoryMessage] = Field(default_factory=list)


class PublicChatResponse(BaseModel):
    """The assistant's reply to a public chat turn."""

    message: str
    citations: list[CitationOut] = Field(default_factory=list)
    confidence: float = 0.0
    low_confidence: bool = False
    agent: str  # knowledge | leave | recruitment | clarify
    confidence_applicable: bool = False
    meta: dict | None = None
    ui_widget: dict | None = None

