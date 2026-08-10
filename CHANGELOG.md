# Changelog

## [0.3.0] - 2026-08-06

### Added

- Ingestion pipeline write side: upload → Document Registry → MinIO → job
  queue → worker → INDEXED
- Ported structure-aware ingestion engine (`validate/parse/normalize/chunk`)
  into `backend/src/app/knowledge/ingestion/` with an in-memory
  `build_normalized()` seam (anydoc parsing, hierarchical small-to-big
  chunking with content hashes)
- ORM persist adapter (`ingestion/persist.py`): hierarchical chunk tree
  (`chunk_level`/`parent_chunk_id`/`ancestors`/`section_path`/`embeddable`),
  leaf-only embeddings, provenance, version bump / `is_current`, in-place
  `FAILED` lifecycle, checksum dedup backstop
- Ingestion worker (`app/jobs/ingestion_worker.py`): `FOR UPDATE SKIP
  LOCKED` claiming, MinIO read, engine → Model Gateway embeddings →
  persist, retry-in-place without re-upload
- Upload/registry orchestration (`ingestion/orchestrator.py`) with
  SHA-256 checksum dedup (`SKIPPED_DUPLICATE`) and MinIO-before-commit
  enqueue (no orphan jobs)
- Knowledge REST API: `POST /documents/upload`, `GET /documents[/{id}]`,
  `GET /jobs/{job_id}`, `POST /jobs/{job_id}/retry`, `GET /search`
- Async-safe MinIO object-store adapter (`integrations/object_store.py`)
- Alembic migration `20260806_0002`: chunk-tree columns + partial unique
  checksum dedup index
- Docker stack (`docker-compose.yml`): postgres+pgvector, MinIO, backend,
  ingestion worker, optional Ollama (`local-models` profile)
- `scripts/e2e_ingestion.py` end-to-end smoke test; CI now runs lint +
  full suite (incl. pgvector integration tests) against a service container
- Fixed: `KnowledgeService.retrieve` runs BM25/vector legs sequentially
  (SQLAlchemy forbids concurrent use of one `AsyncSession`)

### Fixed (retrieval quality)

- BM25 leg now searches leaf rows only (`embeddable = TRUE`): document/section
  context rows whose text merely mentions a phrase can no longer crowd out the
  focused leaf that states it
- Without a reranker model, ordering + confidence use the vector leg's real
  cosine similarity instead of the pass-through's flat 0.5, so the
  low-confidence gate is meaningful again
- Small-to-big expansion: matched leaves are enriched with their enclosing
  section text (`repository.fetch_parent_context`), so the grounded context
  shows the leaf inside its section; the whole-document row is never expanded
  into (context stays focused)
- Reranker wiring fixed: `GET /search` now actually passes `build_reranker()`
  into `KnowledgeService` (previously dead code — `RERANKER_ENABLED=true` had
  no effect). When enabled but the optional `reranker` extra is missing, it
  degrades to pass-through with a loud warning instead of a flat 0.5; the
  Docker image installs the extra and compose enables it with the HF model
  cache persisted via a host volume
- Retrieval funnel widened: per-leg candidates `top_k` 20 → 30 and reranked
  window `rerank_top_n` 5 → 15, so the reranker actually sees sections the
  BM25/vector legs ranked outside the old top-5 (keyword-style sections no
  longer crowd out better semantic matches)
- Confidence is peak-anchored (`0.75 * top score + 0.25 * runner-up`) instead
  of the mean of the top-N, which sigmoid-compressed bge-reranker scores kept
  pinned at ~0.5; the gate threshold is recalibrated 0.50 → 0.55 so one real
  hit (~0.6-0.65) passes while a pile of neutral 0.5s fails
- `bm25_weight`/`vector_weight` were declared but never read; weighted RRF now
  applies them so the lexical vs semantic legs can be rebalanced

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
