# AI HR Assistant

An AI-powered HR assistant for startups/SMEs without a dedicated HR team.
It combines a **grounded RAG knowledge pipeline** (policy Q&A) with
**deterministic HR workflows** — leave management and recruitment with
AI-assisted candidate evaluation.

The backend is built with **FastAPI** and a **PostgreSQL + pgvector**
knowledge/retrieval core: ingestion writes indexed chunks; the Knowledge
Service serves them to the agent with hybrid (BM25 + vector) retrieval,
fusion, reranking, citations, and confidence scoring.

> Detailed design lives in [`inital_docs/`](../inital_docs/) and
> [`docs/`](./docs/). Start with
> [`knowledge_service.md`](../inital_docs/architecture/knowledge_service.md)
> and ADR-0001 (`docs/adr/0001-local-model-serving.md`).

## Layout

```text
ai-hr-assistant/
├── Makefile                  # dev / test / lint (uses backend/.venv)
├── backend/
│   ├── alembic/              # async Alembic migrations
│   ├── pyproject.toml        # deps + `reranker` extra + ruff/pytest config
│   ├── src/app/
│   │   ├── config/           # pydantic-settings (env-driven)
│   │   ├── db/               # engine, session, declarative Base
│   │   ├── knowledge/        # models, contracts, retrieval, ranking,
│   │   │                     # grounding, confidence, service
│   │   ├── model_gateway/    # Embedder/Reranker interfaces + adapters
│   │   └── recruitment/      # recruitment module + swappable Auth
│   └── tests/                # unit + pgvector-backed integration tests
└── docs/
    └── adr/                  # architecture decision records
```

## Stack

- **Frontend**: Next.js (React, Tailwind) — Manager + Candidate portals.
- **Backend**: FastAPI (Python), dependency management via `uv`.
- **Auth**: swappable `AuthProvider` interface — `dev_stub` (default) or Keycloak (`start-dev`).
- **Database**: PostgreSQL (+ pgvector); **MinIO** for resumes; **Mailpit** for dev email.
- **AI scoring**: hosted Ollama API via Model Gateway; deterministic keyword fallback when no key is set.
- **Jobs**: PostgreSQL-backed transactional outbox + worker.

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

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
| `DATABASE_URL` | `postgresql+psycopg2://hr:hr@localhost:5432/hr_assistant` | app DB |
| `TEST_DATABASE_URL` | — | pgvector integration tests (skipped if unset) |
| `AUTH_PROVIDER` | `dev_stub` | `dev_stub` \| `keycloak` |
| `MINIO_ENDPOINT` | `minio:9000` | S3-compatible resume object store |
| `OLLAMA_URL` | `http://localhost:11434` | embedding server |
| `EMBEDDING_MODEL` | `nomic-embed-text` | embedding model (768-dim) |
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

```bash
make dev          # uvicorn with reload (backend/.venv/bin/uvicorn)
```

Or start the full Docker stack (Postgres+pgvector, Keycloak, MinIO, backend,
worker, Ollama, ...) — see
[`docker_infrastructure.md`](../inital_docs/architecture/docker_infrastructure.md):

```bash
docker compose --profile dev --profile local-models up -d
```

## Recruitment module

Manager portal: post vacancies, review applications (AI score + overview +
resume), and approve (shortlist) or reject. Candidate portal: browse open
vacancies, apply by uploading a resume (PDF/DOCX), and track application
status. Emails go through the transactional outbox — written in the same DB
transaction as the decision, so notifications can't be silently lost.

## Tests & lint

```bash
make test      # pytest backend/tests
make lint      # ruff check backend/src
```

Integration tests against a real pgvector DB are gated on `TEST_DATABASE_URL`;
without it they skip (e.g. run against a throwaway container:
`docker run -p 55432:5432 -e POSTGRES_USER=hr -e POSTGRES_PASSWORD=hr
-e POSTGRES_DB=test_hr pgvector/pgvector:pg16`).

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