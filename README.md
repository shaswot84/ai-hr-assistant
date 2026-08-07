# AI HR Assistant

An AI-powered HR assistant built with **FastAPI** (backend) and a
**PostgreSQL + pgvector** knowledge/retrieval core. The MVP includes a
grounded RAG pipeline: ingestion writes indexed chunks (upload → MinIO →
parse/chunk → embed → pgvector + FTS); the Knowledge Service serves them
to the agent with hybrid (BM25 + vector) retrieval, fusion, reranking,
citations, and confidence scoring.

> Detailed design lives in [`inital_docs/`](../inital_docs/) and
> [`docs/`](./docs/). Start with
> [`knowledge_service.md`](../inital_docs/architecture/knowledge_service.md)
> and ADR-0001 (`docs/adr/0001-local-model-serving.md`).

## Layout

```text
ai-hr-assistant/
├── Makefile                  # dev / test / lint (uses backend/.venv)
├── docker-compose.yml        # postgres+pgvector / minio / backend / worker (+ optional ollama)
├── scripts/
│   └── e2e_ingestion.py      # end-to-end smoke test (needs the running stack)
├── backend/
│   ├── alembic/              # async Alembic migrations
│   ├── pyproject.toml        # deps + `reranker` extra + ruff/pytest config
│   ├── src/app/
│   │   ├── api/knowledge.py  # ingestion + retrieval REST endpoints
│   │   ├── config/           # pydantic-settings (env-driven)
│   │   ├── db/               # async engine, session, declarative Base
│   │   ├── integrations/     # object_store adapter (MinIO, async-safe)
│   │   ├── jobs/             # ingestion_worker (claim → process → INDEXED)
│   │   ├── knowledge/        # models, contracts, retrieval, ranking,
│   │   │   ├── ingestion/    #   grounding, confidence, service
│   │   │   │                 #   validate/parse/normalize/chunk engine,
│   │   │   │                 #   orchestrator (upload/registry), persist
│   │   │   └── ...           #   (ORM write adapter)
│   │   └── model_gateway/    # Embedder/Reranker interfaces + adapters
│   └── tests/                # unit + pgvector-backed integration tests
└── docs/
    └── adr/                  # architecture decision records
```

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) only if you
want to run the backend natively. The easiest path is Docker:

```bash
./run.sh        # builds & starts the whole stack, waits for health, opens the UI
```

`run.sh` checks Docker, reuses a native Ollama on `:11434` if one is running
(otherwise it starts the containerized Ollama and pulls `nomic-embed-text`),
then runs `docker compose up -d --build` and waits until the backend and
frontend are healthy. Ports/creds come from `.env` (see `.env.example`)..

Stop everything with `docker compose down` (add `-v` to also wipe data).

Native (API only):

```bash
cd backend
uv sync --extra dev                # dev/test dependencies
uv sync --extra dev --extra reranker   # + sentence-transformers (torch)
```

Copy the env template and adjust:

```bash
cp .env.example .env   # at repo root
```

Key variables (see `config/settings.py` for defaults):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://hr:hr@localhost:5432/hr_assistant` | app DB |
| `TEST_DATABASE_URL` | — | pgvector integration tests (skipped if unset) |
| `MINIO_ENDPOINT` | `localhost:9000` | S3 API endpoint (compose maps to host `9100`) |
| `MINIO_BUCKET` | `hr-documents` | bucket for authoritative document bytes |
| `OLLAMA_URL` | `http://localhost:11434` | embedding server |
| `EMBEDDING_MODEL` | `nomic-embed-text` | embedding model (768-dim) |
| `INGESTION_POLL_INTERVAL_SECONDS` | `5` | worker queue poll interval |
| `RERANKER_ENABLED` | `true` | on/off for in-process reranker |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | cross-encoder reranker |

## Database & migrations

Requires Postgres with the `pgvector` extension (the
`pgvector/pgvector:pg16` Docker image includes it).

```bash
cd backend
alembic upgrade head     # apply migrations
alembic downgrade base   # roll back
```

## Running

Native (API only):

```bash
make dev          # uvicorn with reload (backend/.venv/bin/uvicorn)
```

Or the full Docker stack — Postgres+pgvector, MinIO, backend, and the
ingestion worker (Ollama is opt-in behind the `local-models` profile since
it pulls ~2.5 GB of weights):

```bash
docker compose up -d                              # postgres + minio + backend + worker
docker compose --profile local-models up -d       # + ollama
ollama pull nomic-embed-text                      # first run (or: docker compose exec ollama ollama pull nomic-embed-text)
```

## Ingestion pipeline (write side)

```text
POST /api/knowledge/documents/upload  (bytes)
        │  SHA-256 checksum dedup → SKIPPED_DUPLICATE if already INDEXED
        ▼
Document Registry (document / version rows)  +  MinIO (authoritative object_key)
        │
        ▼
ingestion_job (PENDING) ──► worker claims (FOR UPDATE SKIP LOCKED)
        │                      │
        │        validate → parse → normalize → chunk   (knowledge/ingestion/)
        │        embed leaves via Model Gateway (Ollama nomic-embed-text)
        │        persist chunk tree + provenance → INDEXED
        ▼
Hybrid index (pgvector + FTS) served by the Knowledge Service
```

- The worker (`python -m app.jobs.ingestion_worker`) polls the queue and
  processes jobs; failures are recorded **in place** (`FAILED` +
  `failure_reason`) and are retryable without re-uploading
  (`POST /api/knowledge/jobs/{job_id}/retry`).
- The same bytes re-uploaded anywhere are skipped (`SKIPPED_DUPLICATE`), and
  re-uploading changed bytes of an existing title creates a new version
  (previous INDEXED version kept servable until the new one is ready).
- REST surface: `POST /documents/upload`, `GET /documents[/{id}]`,
  `GET /jobs/{job_id}`, `POST /jobs/{job_id}/retry`, `GET /search`.

End-to-end smoke test against a running stack:

```bash
backend/.venv/bin/python scripts/e2e_ingestion.py
```

## Tests & lint

```bash
make test      # pytest backend/tests
make lint      # ruff check backend/src
```

Integration tests against a real pgvector DB are gated on `TEST_DATABASE_URL`;
without it they skip (e.g. run against a throwaway container:
`docker run -p 55432:5432 -e POSTGRES_USER=hr -e POSTGRES_PASSWORD=hr
-e POSTGRES_DB=test_hr pgvector/pgvector:pg16`, then
`TEST_DATABASE_URL=postgresql+asyncpg://hr:hr@localhost:55432/test_hr
pytest backend/tests`). CI runs them against a pgvector service container.

## Model serving

- **Embedding** (`nomic-embed-text`) is served by Ollama via
  `POST /api/embed` (`model_gateway/embedder.py`).
- **Reranking** (`BAAI/bge-reranker-base`) runs in-process via
  `sentence-transformers` (`model_gateway/reranker.py`); it is optional and
  falls back to a pass-through reranker when `RERANKER_ENABLED=false`.

Pull the embedding model once:

```bash
ollama pull nomic-embed-text
```

## Architecture summary

```text
Agent ──► Knowledge Service ──► Hybrid Retrieval (BM25 + pgvector)
              │                        │
              │                  Reciprocal Rank Fusion
              │                        │
              │                   Reranker (bge-reranker-base)
              │                        │
              │              Grounding + Citations + Confidence
              ▼                        ▼
         (LLM prompt)          low-confidence → knowledge review task

Knowledge Service talks only to PostgreSQL; it never touches MinIO,
pgvector, or the FTS indexes directly.
```
