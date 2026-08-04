# ADR-0001: Serve Embeddings via Ollama and the Reranker In-Process

## Status

Accepted

## Context

The retrieval stack requires two local models behind the Model Gateway:

- An embedding model for pgvector semantic search (`nomic-embed-text`, 768-dim).
- A cross-encoder reranker over the fused BM25 + vector candidate set
  (`BAAI/bge-reranker-base`).

Both could be served by Ollama, or both in-process, or a mix. The choice
affects the `docker-compose.yaml` (extra container vs. extra process memory),
the backend image dependencies, and the Model Gateway adapters.

Key facts:

- Ollama's HTTP API (`POST /api/embed`) is a stable, well-supported surface for
  embedding models. The infra compose already defines an `ollama` service and
  sets `OLLAMA_URL` on the backend/worker.
- `bge-reranker-base` is a BERT cross-encoder. Ollama's model runner does not
  support cross-encoders (its reranker support is a separate, immature engine),
  so serving it through Ollama is not viable today.
- Loading a sentence-transformers `CrossEncoder` pulls in torch (~1–2 GB of
  weights + significant memory in-process).

## Decision

- **Embedding** (`nomic-embed-text`): served by Ollama over HTTP
  (`OllamaEmbedder` gateway adapter, `POST /api/embed`, L2-normalized output).
- **Reranking** (`BAAI/bge-reranker-base`): loaded in-process in the
  backend/worker via `sentence-transformers` `CrossEncoder`
  (`SentenceTransformerReranker` gateway adapter). `predict` runs on a worker
  thread; raw logits are squashed to `[0, 1]` with sigmoid.

The reranker is an optional dependency (`reranker` extra) and is disabled when
`RERANKER_ENABLED=false`, in which case the Knowledge Service falls back to a
pass-through reranker (BM25 + RRF scores only).

## Consequences

### Positive

- Embedding serving reuses the existing Ollama container and HTTP surface; no
  extra server process for a lightweight 137M-param model.
- The cross-encoder is served in a way it actually supports, on the same host
  as the caller (no network hop, no NaN/instability risk from an immature
  reranker engine).
- Both adapters implement the `Embedder` / `Reranker` interfaces and are wired
  from configuration, so the deployment strategy stays replaceable.

### Negative

- The reranker adds torch and ~1–2 GB of weights to the backend image and
  in-process memory. This is why it is an optional extra and gated behind a
  config flag.
- Workers must cache the Hugging Face weights (or pre-bake them into the image)
  to avoid re-downloads; cold-start latency on first rerank is significant.
- If the embedding model is upgraded to a much larger one, Ollama memory grows
  and may need re-tuning.

## Alternatives Considered

- **Both in-process**: would require packaging the embedding model as well,
  duplicating what Ollama already provides cleanly.
- **Both via Ollama**: not possible today for cross-encoders; would couple the
  reranker to an immature and unstable engine.
- **Reranker via a separate microservice**: heavier infrastructure than an MVP
  warrants; contradicts the modular-monolith direction.
