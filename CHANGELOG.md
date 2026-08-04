# Changelog

## [0.2.0] - 2026-08-04

### Added

- Knowledge Service foundation: RAG models (document, document_version,
  document_chunk, ingestion_job), async Alembic migration with GIN full-text
  and HNSW vector indexes, and read-only hybrid retrieval repository gated on
  INDEXED versions
- RRF fusion, reranker abstraction, grounding/citation builder, and confidence
  estimation with low-confidence gate
- Shared contracts (RetrievedChunk, IngestionProvenance, KnowledgeResult) and
  Model Gateway interfaces
- Model serving behind the gateway: OllamaEmbedder (Ollama `/api/embed`,
  nomic-embed-text, 768-dim) and in-process SentenceTransformerReranker
  (BAAI/bge-reranker-base) with pass-through fallback
- Config settings (DB, embedding, retrieval, reranker, model gateway) and
  optional `reranker` extra (sentence-transformers)
- Unit tests and pgvector-backed integration tests

## [0.1.0] - 2026-07-30

### Added

- Project scaffold
