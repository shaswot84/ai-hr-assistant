"""Unit tests for OllamaCloudLLM using an httpx MockTransport."""

import json

import httpx
import pytest

from app.model_gateway.llm import OllamaCloudLLM


@pytest.mark.asyncio
async def test_complete_posts_chat_payload_and_returns_content():
    """Verifies the request body/URL and parsed completion."""
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={"message": {"content": "Employees get 20 days of annual leave."}},
        )

    client = httpx.AsyncClient(
        base_url="https://ollama.com", transport=httpx.MockTransport(handler)
    )
    llm = OllamaCloudLLM(
        "https://ollama.com",
        "sk-test",
        "gpt-oss:120b-cloud",
        client=client,
    )

    answer = await llm.complete("You are an HR assistant.", "How much leave?")

    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "gpt-oss:120b-cloud"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "You are an HR assistant."},
        {"role": "user", "content": "How much leave?"},
    ]
    assert answer == "Employees get 20 days of annual leave."

    await llm.aclose()


@pytest.mark.asyncio
async def test_complete_raises_on_error_status():
    """Non-2xx responses raise HTTPStatusError instead of returning garbage."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = httpx.AsyncClient(
        base_url="https://ollama.com", transport=httpx.MockTransport(handler)
    )
    llm = OllamaCloudLLM("https://ollama.com", "sk-bad", "gpt-oss:120b-cloud", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        await llm.complete("system", "user")

    await llm.aclose()
