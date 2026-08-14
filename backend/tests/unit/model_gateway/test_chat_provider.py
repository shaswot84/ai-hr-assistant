"""Unit tests for OllamaChatProvider (the leave agent's dispatch model).

Covers the settings fallback (chat settings ``OLLAMA_CHAT_*`` fall back to the
generation LLM settings ``LLM_*`` so a single configured key serves both
agents), the configured/unconfigured gate, and the JSON completion contract.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import app.model_gateway.ollama as ollama_module
from app.model_gateway.ollama import OllamaChatProvider


def _settings(*, chat_api_key: str = "", llm_api_key: str = "", chat_configured: bool = True) -> SimpleNamespace:
    """chat_configured=False models a deployment that only sets LLM_*."""
    return SimpleNamespace(
        chat=SimpleNamespace(
            api_base="https://chat.example.com" if chat_configured else "",
            api_key=chat_api_key,
            model="chat-model" if chat_configured else "",
            request_timeout=30.0,
        ),
        llm=SimpleNamespace(
            url="https://llm.example.com",
            api_key=llm_api_key,
            model="llm-model",
        ),
    )


def test_chat_settings_win_when_configured(monkeypatch):
    """OLLAMA_CHAT_* settings take precedence when set."""
    monkeypatch.setattr(
        ollama_module, "get_settings", lambda: _settings(chat_api_key="chat-key")
    )
    provider = OllamaChatProvider()
    assert provider.is_configured() is True
    assert provider._base == "https://chat.example.com"
    assert provider._api_key == "chat-key"
    assert provider._model == "chat-model"


def test_falls_back_to_generation_llm_settings(monkeypatch):
    """Only LLM_* configured (the current deployment) -> the provider uses it,
    so the leave agent's dispatch loop is not broken by a missing
    OLLAMA_CHAT_API_KEY."""
    monkeypatch.setattr(
        ollama_module,
        "get_settings",
        lambda: _settings(llm_api_key="llm-key", chat_configured=False),
    )
    provider = OllamaChatProvider()
    assert provider.is_configured() is True
    assert provider._base == "https://llm.example.com"
    assert provider._api_key == "llm-key"
    assert provider._model == "llm-model"


def test_unconfigured_without_any_key(monkeypatch):
    """No key anywhere -> is_configured() is False (turns fail fast, honestly)."""
    monkeypatch.setattr(ollama_module, "get_settings", lambda: _settings())
    assert OllamaChatProvider().is_configured() is False


@pytest.mark.asyncio
async def test_complete_json_posts_and_parses(monkeypatch):
    """The provider hits /v1/chat/completions and returns the parsed JSON."""
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"action": "reply", "reply": "hi", "tool": null, "args": {}}'
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://llm.example.com", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(
        ollama_module,
        "get_settings",
        lambda: _settings(llm_api_key="llm-key", chat_configured=False),
    )
    provider = OllamaChatProvider(client=client)

    parsed = await provider.complete_json(system_prompt="sys", user_prompt="usr")

    assert captured["url"] == "https://llm.example.com/v1/chat/completions"
    assert captured["auth"] == "Bearer llm-key"
    assert captured["body"]["model"] == "llm-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert parsed == {"action": "reply", "reply": "hi", "tool": None, "args": {}}
    await client.aclose()
