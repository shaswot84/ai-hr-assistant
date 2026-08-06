# AI HR Assistant

An AI-powered HR assistant for startups/SMEs without a dedicated HR team.
It combines a **grounded RAG knowledge pipeline** (policy Q&A) with
**deterministic HR workflows** — leave management and recruitment with
AI-assisted candidate evaluation.

The backend is built with **FastAPI** and a **PostgreSQL + pgvector**
knowledge/retrieval core: ingestion writes indexed chunks; the Knowledge
Service serves them to the agent with hybrid (BM25 + vector) retrieval,
fusion, reranking, citations, and confidence scoring.

> Detailed design lives one level up in [`hr-project-docs/`](../hr-project-docs/)
> (see its `README.md` for reading order) and in [`docs/`](./docs/), which has
> ADR-0001 (`docs/adr/0001-local-model-serving.md`) plus the auth/recruitment
> plan docs (`docs/plan-auth.md`, `docs/plan-recruitment.md`).

## Layout

```text
ai-hr-assistant/
├── Makefile                  # up / migrate / seed / test / lint (uses backend/.venv)
├── backend/
│   ├── alembic/              # migrations: RAG schema, then identity/recruitment/infra schema
│   ├── pyproject.toml        # deps + `reranker` extra + ruff/pytest config
│   ├── src/app/
│   │   ├── config/           # pydantic-settings (env-driven)
│   │   ├── db/                # session.py = async engine (Knowledge Service + Alembic);
│   │   │                      # sync_session.py = sync engine (auth/recruitment)
│   │   ├── knowledge/        # models, contracts, retrieval, ranking, grounding,
│   │   │                     # confidence, service (RAG) + resume_extraction (recruitment)
│   │   ├── model_gateway/    # Embedder/Reranker/Chat provider interfaces + adapters
│   │   ├── auth/             # self-issued JWT AuthProvider (passwords, jwt, provider)
│   │   ├── domain/           # SQLAlchemy models: identity/org, recruitment, outbox, audit, setting
│   │   ├── capabilities/     # business logic: recruitment, settings
│   │   ├── repositories/     # data access for the domain models
│   │   ├── services/         # identity resolution (UserContext -> Employee/Candidate)
│   │   ├── evaluation/       # LLM resume-vs-job scoring (+ deterministic fallback)
│   │   ├── jobs/              # outbox worker (AI evaluation + email jobs)
│   │   ├── integrations/     # MinIO object store, SMTP email
│   │   └── shared/           # Clock abstraction
│   └── tests/                # unit + pgvector-backed integration tests
├── frontend/                 # Next.js App Router — login, manager & candidate portals
└── docs/
    ├── adr/                  # architecture decision records
    ├── plan-auth.md
    └── plan-recruitment.md
```

## Stack

- **Frontend**: Next.js (App Router, React, Tailwind CSS v4) — role-aware login + Manager/Candidate portals in one app.
- **Backend**: FastAPI (Python), dependency management via `uv`. Two SQLAlchemy engines share one Postgres and one `Base.metadata`: an **async** engine (`db/session.py`, asyncpg) for the Knowledge Service and Alembic, and a **sync** engine (`db/sync_session.py`, psycopg2) for the auth/recruitment stack — both derived from a single `DATABASE_URL`.
- **Auth**: **self-issued JWT** behind a swappable `AuthProvider` interface. The backend signs short-lived HS256 access tokens after verifying email+password against the `application_user` table (PBKDF2-hashed, 600k iterations). No external IdP, cloud dependency, or webhook — works on every localhost clone. Coarse roles (`HR_ADMIN`/`EMPLOYEE`/`CANDIDATE`) are read from the DB on every request and enforced in FastAPI (see `hr-project-docs/architecture/high_level_architecture.md` §4 — this project uses JWT in place of the doc's Keycloak, an explicit team decision).
- **Database**: PostgreSQL (+ pgvector); **MinIO** for resumes; **Mailpit** for dev email.
- **AI scoring**: hosted Ollama API via the Model Gateway; deterministic keyword-overlap fallback when no API key is set, so the pipeline stays demoable offline.
- **Jobs**: PostgreSQL-backed transactional outbox + worker (`SELECT ... FOR UPDATE SKIP LOCKED` claiming, so multiple worker replicas never double-process a job).
- **Audit**: append-only `audit_log` table, written from the capability layer on every mutating action (login, vacancy create/close/reopen, apply, decision).

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
| `DATABASE_URL` | `postgresql+asyncpg://hr:hr@localhost:5432/hr_assistant` | app DB (asyncpg; the sync engine derives its own psycopg2 URL from this) |
| `TEST_DATABASE_URL` | — | pgvector integration tests (skipped if unset) |
| `AUTH_PROVIDER` | `jwt` | `jwt` only (others rejected) |
| `JWT_SECRET_KEY` | — | HS256 signing secret (set a long random value) |
| `JWT_ALGORITHM` | `HS256` | signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | token lifetime (short; role re-read from DB per request) |
| `MINIO_ENDPOINT` | `minio:9000` | S3-compatible resume object store |
| `SMTP_HOST` / `SMTP_PORT` | `mailpit` / `1025` | dev email sink (Mailpit UI: `:8025`) |
| `OLLAMA_CHAT_API_KEY` | — | hosted Ollama key for resume scoring (unset → deterministic keyword fallback) |
| `OLLAMA_URL` | `http://localhost:11434` | embedding server |
| `EMBEDDING_MODEL` | `nomic-embed-text` | embedding model (768-dim) |
| `RERANKER_ENABLED` | `true` | on/off for in-process reranker |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | cross-encoder reranker |

## Database & migrations

Requires Postgres with the `pgvector` extension (the
`pgvector/pgvector:pg16` Docker image includes it). Migrations are the real
schema-management path (not `create_all()`, which only exists as a dev
fallback):

```bash
cd backend
alembic upgrade head     # apply migrations (RAG schema, then identity/recruitment/infra schema)
alembic downgrade base   # roll back everything
```

Or via Docker, against the running `postgres` service:

```bash
make migrate
```

## Running

Full stack via Docker (Postgres+pgvector, MinIO, Mailpit, backend, worker, frontend):

```bash
make up      # copies .env if missing, builds, migrates, starts everything, seeds demo data
```

This brings up `http://localhost:3000` (frontend), `http://localhost:8000/docs`
(API), `http://localhost:8025` (Mailpit), `http://localhost:9001` (MinIO
console). Demo accounts after `make seed`: `manager@example.com` /
`manager123` (HR_ADMIN) and `candidate@example.com` / `candidate123`
(CANDIDATE).

Backend only, without Docker:

```bash
make dev          # uvicorn with reload (backend/.venv/bin/uvicorn)
```

## Auth & recruitment module

**Auth**: `/login` takes email + password; the backend verifies against
`application_user.password_hash` and issues a JWT. The frontend stores the
token in `localStorage` and attaches it as `Authorization: Bearer` on every
request; the root route dispatches by role (`HR_ADMIN → /manager`,
`CANDIDATE → /candidate`, `EMPLOYEE → /employee`, a placeholder until the
Leave module lands).

**Recruitment**: Manager portal — post vacancies, close/reopen them, review
applications (AI score + overview + resume download), and approve
(shortlist) or reject. Candidate portal — browse open vacancies, apply by
uploading a resume only (PDF/DOCX, 10MB max), and track application status.
Resume text is extracted (`knowledge/resume_extraction.py`) and scored
against the job title/description by an LLM with a manager-editable system
prompt (`/manager/settings`); emails go through the transactional outbox —
written in the same DB transaction as the decision, so a decision can never
be made without its notification eventually being sent (and never re-sent,
since a decision is only valid once — see `capabilities/recruitment.py`).

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