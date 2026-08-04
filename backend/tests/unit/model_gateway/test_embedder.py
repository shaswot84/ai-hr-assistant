import httpx
import pytest

from app.model_gateway.embedder import OllamaEmbedder, l2_normalize


def test_l2_normalize():
    vec = [3.0, 4.0]
    norm = l2_normalize(vec)
    assert norm[0] == pytest.approx(0.6)
    assert norm[1] == pytest.approx(0.8)
    assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]


@pytest.mark.asyncio
async def test_embed_posts_expected_payload_and_normalizes():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"model": "nomic-embed-text", "embeddings": [[3.0, 4.0], [1.0, 0.0]]},
        )

    client = httpx.AsyncClient(
        base_url="http://ollama:11434", transport=httpx.MockTransport(handler)
    )
    embedder = OllamaEmbedder("http://ollama:11434", "nomic-embed-text", client=client)

    vectors = await embedder.embed(["a", "b"])

    assert captured["url"] == "http://ollama:11434/api/embed"
    import json

    body = json.loads(captured["body"])
    assert body["model"] == "nomic-embed-text"
    assert body["input"] == ["a", "b"]
    assert vectors[0][0] == pytest.approx(0.6)
    assert vectors[1] == [1.0, 0.0]

    await embedder.aclose()


@pytest.mark.asyncio
async def test_embed_applies_task_prefix():
    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.read())
        assert body["input"] == ["search_query: vacation days"]
        return httpx.Response(
            200, json={"embeddings": [[1.0, 0.0] for _ in body["input"]]}
        )

    client = httpx.AsyncClient(
        base_url="http://ollama:11434", transport=httpx.MockTransport(handler)
    )
    embedder = OllamaEmbedder("http://ollama:11434", "nomic-embed-text", client=client)

    await embedder.embed(["vacation days"], prefix="search_query: ")

    await embedder.aclose()


@pytest.mark.asyncio
async def test_embed_raises_on_error_status():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    client = httpx.AsyncClient(
        base_url="http://ollama:11434", transport=httpx.MockTransport(handler)
    )
    embedder = OllamaEmbedder("http://ollama:11434", "nope", client=client)

    with pytest.raises(httpx.HTTPStatusError):
        await embedder.embed(["x"])

    await embedder.aclose()
