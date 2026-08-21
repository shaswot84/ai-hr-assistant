# AI HR Assistant 🤖💼

[![FastAPI](https://img.shields.io/badge/FastAPI-0.130+-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-15+-black.svg?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20%26%20Cloud-white.svg?style=flat-square&logo=ollama&logoColor=black)](https://ollama.com)
[![Arize Phoenix](https://img.shields.io/badge/Arize%20Phoenix-Observability-ff6b6b.svg?style=flat-square)](https://phoenix.arize.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)

An enterprise-grade, open-source AI HR Assistant designed for startups and SMEs without a dedicated HR department. It combines an **agentic LangGraph supervisor workflow**, a **high-precision grounded RAG knowledge pipeline** (policy Q&A with citations and reranking), and **deterministic HR workflows** for leave management, applicant tracking (ATS) with AI resume evaluation, organizational directory management, and full audit logging.

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
  - [1. Multi-Agent Supervisor Workflow](#1-multi-agent-supervisor-workflow)
  - [2. Grounded RAG Knowledge Pipeline](#2-grounded-rag-knowledge-pipeline)
  - [3. Transactional Outbox & Async Jobs](#3-transactional-outbox--async-jobs)
- [Tech Stack](#-tech-stack)
- [Directory Layout](#-directory-layout)
- [Quick Start](#-quick-start)
  - [Prerequisites](#prerequisites)
  - [One-Command Docker Setup (Recommended)](#one-command-docker-setup-recommended)
  - [Demo Accounts](#demo-accounts)
- [Portals & User Journeys](#-portals--user-journeys)
  - [👔 Manager / HR Admin Portal](#-manager--hr-admin-portal)
  - [👤 Employee Portal](#-employee-portal)
  - [📄 Candidate Portal](#-candidate-portal)
- [Native Local Development](#-native-local-development)
  - [Backend Setup (with `uv`)](#backend-setup-with-uv)
  - [Frontend Setup](#frontend-setup)
- [Configuration & Environment Variables](#-configuration--environment-variables)
- [REST API Reference](#-rest-api-reference)
- [Testing & Quality Assurance](#-testing--quality-assurance)
- [AI Observability & Tracing](#-ai-observability--tracing)

---

## ✨ Key Features

| Capability | Highlights |
|---|---|
| 🧠 **Multi-Agent Supervisor System** | LangGraph-powered orchestration with specialized sub-agents (`KnowledgeAgent`, `LeaveAgent`, `RecruitmentAgent`, `ClarifyNode`, `RecapNode`). Automatic multi-turn conversation memory, intent routing, and graceful disambiguation. |
| 📚 **Grounded RAG Knowledge Engine** | Dual-leg hybrid retrieval (**BM25 lexical + pgvector semantic**), Reciprocal Rank Fusion (RRF), cross-encoder reranker (`BAAI/bge-reranker-base`), small-to-big context expansion, citations, and confidence score gating. |
| 🌴 **Deterministic Leave Management** | Natural language leave requests (e.g. *"take 3 days off next Monday"*), relative date resolution, real-time balance calculations, staged confirmation gates (`staged → confirmed`), and Redis-backed execution locks preventing race conditions. |
| 🎯 **AI Recruitment & Resume Screening** | ATS resume parsing (PDF/DOCX), automated LLM candidate-job matching (scores, key factor breakdown, strengths/weaknesses), editable manager scoring prompts, and 1-click candidate-to-employee onboarding. |
| ✉️ **Guaranteed Notifications (Outbox)** | Transactional Outbox pattern with `SELECT ... FOR UPDATE SKIP LOCKED` worker queues for bulletproof email delivery (welcome, application receipt, interview alerts, decision notices). |
| 🏢 **People & Organization Directory** | Complete department, designation, and employee hierarchy tracking with manager-subordinate relationships and self-service profile views. |
| 🛡️ **Enterprise Safety & Guardrails** | Multi-layer output safety: PII masking, grounded evidence checking, citation validation, off-topic detection, and optional LLM safety judges. |
| 🔒 **Self-Issued JWT & RBAC** | Self-contained HS256 JWT auth with PBKDF2 (600,000 rounds) password hashing. Zero external identity provider dependencies. Role-Based Access Control (`HR_ADMIN`, `EMPLOYEE`, `CANDIDATE`). |
| 🔍 **Full Observability & Audit Trail** | Native **Arize Phoenix** integration with OpenTelemetry and OpenInference tracing across multi-agent chains and RAG queries, plus append-only database audit logs. |

---

## 🏛️ System Architecture

### 1. Multi-Agent Supervisor Workflow

The chat interface routes user queries through a **LangGraph supervisor graph** that isolates deterministic operations from non-deterministic LLM generations:

```text
User Message ──► Authentication & Session Resolution
                        │
                        ▼
            ┌───────────────────────┐
            │   Supervisor Agent    │ (Intent classification / keyword heuristic / recap)
            └───────────┬───────────┘
                        │
       ┌────────────────┼────────────────┬────────────────┐
       ▼                ▼                ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Knowledge  │  │    Leave    │  │ Recruitment │  │   Clarify   │
│    Agent    │  │    Agent    │  │    Agent    │  │   / Recap   │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       │          ┌─────┴──────┐         │                │
       │          │ 100% Pre-  │         │                │
       │          │ flight &   │         │                │
       │          │ Staging    │         │                │
       │          └─────┬──────┘         │                │
       ▼                ▼                ▼                ▼
┌───────────────────────────────────────────────────────────────┐
│              Output Safety & Guardrails Pipeline              │
│    (PII Masking • Grounding Evidence • Citations • Judge)     │
└───────────────────────────────┬───────────────────────────────┘
                                ▼
                       Grounded Response
```

### 2. Grounded RAG Knowledge Pipeline

```text
[ Document Upload ] (Markdown / PDF / Text)
        │
        ▼
[ SHA-256 Checksum Dedup ] ──(Duplicate)──► SKIPPED_DUPLICATE
        │ (New / Changed)
        ▼
[ MinIO Object Storage ] + [ Document Registry (PostgreSQL) ]
        │
        ▼
[ Ingestion Queue (ingestion_job) ]
        │
        ▼  Worker claims (SELECT ... FOR UPDATE SKIP LOCKED)
[ Structure-Aware Parsing & Chunking ] (Hierarchical Small-to-Big)
        │
        ▼
[ Model Gateway (Ollama nomic-embed-text) ] (Leaf-only 768-dim embeddings)
        │
        ▼
[ Hybrid PostgreSQL Index ]
   ├── HNSW Vector Index (pgvector cosine similarity)
   └── GIN Full-Text Index (BM25 lexical matching)
        │
        ▼
═══════════════════════════════════════════════════════════════════
[ Query Retrieval Flow ]
        │
        ├──► BM25 Lexical Leg (Top 30) ────┐
        └──► Vector Semantic Leg (Top 30) ──┴─► Reciprocal Rank Fusion (RRF)
                                                       │
                                                       ▼
                                            Cross-Encoder Reranker
                                            (BAAI/bge-reranker-base)
                                                       │
                                                       ▼
                                            Small-to-Big Context Expansion
                                            (Fetch Parent Section Context)
                                                       │
                                                       ▼
                                            Confidence Gating (Threshold 0.40+)
                                                       │
                                                       ▼
                                            Grounded Context + Citations ──► LLM
```

### 3. Transactional Outbox & Async Jobs

- **Ingestion Worker (`app.jobs.ingestion_worker`)**: Polls and indexes new HR documents asynchronously. Failures are stored in-place and retryable via API.
- **Recruitment Worker (`app.jobs.worker`)**: Evaluates candidate resumes against job vacancies using LLMs and delivers transactional notification emails via SMTP (Mailpit in development).
- **Concurrency Protection**: Both workers claim tasks with `FOR UPDATE SKIP LOCKED`, allowing safe horizontal scaling without race conditions.

---

## 🛠️ Tech Stack

### Backend
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) with asynchronous request handling.
- **Database & ORM**: PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector), [SQLAlchemy 2.0 (asyncpg)](https://www.sqlalchemy.org/), [Alembic](https://alembic.sqlalchemy.org/) async migrations.
- **Multi-Agent Orchestration**: [LangGraph](https://langchain-ai.github.io/langgraph/) & [LangChain](https://www.langchain.com/).
- **Model Gateway & Embeddings**: [Ollama](https://ollama.com/) (`nomic-embed-text`), [Sentence-Transformers](https://www.sbert.net/) (`BAAI/bge-reranker-base`).
- **Object Storage**: [MinIO](https://min.io/) (S3-compatible bucket storage for resumes and policy files).
- **Cache & Locks**: [Redis 7](https://redis.io/) (chat workflow session state and cross-process concurrency locks).
- **Email Service**: [aiosmtplib](https://github.com/cole/aiosmtplib) with [Mailpit](https://mailpit.axllent.org/) dev server.
- **Observability**: [Arize Phoenix](https://phoenix.arize.com/) with [OpenTelemetry](https://opentelemetry.io/) & [OpenInference](https://github.com/Arize-ai/openinference).

### Frontend
- **Framework**: [Next.js 15+](https://nextjs.org/) (App Router, Server & Client Components).
- **UI & Styling**: [React 19](https://react.dev/), [Tailwind CSS v4](https://tailwindcss.com/).
- **Markdown & Citations**: `react-markdown`, `remark-gfm`.

---

## 📁 Directory Layout

```text
ai-hr-assistant/
├── Makefile                      # One-command orchestration (up, down, migrate, seed, test, lint)
├── docker-compose.yml            # Multi-container orchestration (postgres, minio, mailpit, redis, backend, workers, frontend, phoenix)
├── run.sh                        # Interactive automated bootstrap script
├── .env.example                  # Environment configuration template
│
├── backend/
│   ├── alembic/                  # Async Alembic database migrations
│   ├── pyproject.toml            # Dependencies and tools (uv, ruff, pytest)
│   ├── sample_docs/              # HR policy corpus (annual leave, dress code, sick leave, onboarding, etc.)
│   ├── src/app/
│   │   ├── main.py               # FastAPI entrypoint and lifespan management
│   │   ├── agents/               # LangGraph multi-agent implementation
│   │   │   ├── supervisor/       # Supervisor routing graph and state definitions
│   │   │   ├── knowledge_agent/  # RAG policy retrieval agent node
│   │   │   ├── leave_agent/      # Deterministic leave booking, balance, and confirmation node
│   │   │   └── recruitment_agent/# Job inquiry and application status node
│   │   ├── api/                  # REST API routes
│   │   │   ├── routes/           # auth, chat, leave, recruitment, people, settings, audit
│   │   │   └── knowledge.py      # document ingestion, search, and job management
│   │   ├── auth/                 # Self-issued HS256 JWT provider & PBKDF2 hasher
│   │   ├── capabilities/         # Domain business logic (leave, recruitment, people, settings)
│   │   ├── domain/               # SQLAlchemy ORM models (identity, leave, recruitment, outbox, audit)
│   │   ├── evaluation/           # LLM resume screening, match scoring, and keyword suggestions
│   │   ├── integrations/         # S3/MinIO async/sync object stores, SMTP mailer
│   │   ├── jobs/                 # Ingestion worker & recruitment outbox worker
│   │   ├── knowledge/            # Structure-aware chunking, hybrid retrieval repo, RRF fusion, service
│   │   ├── model_gateway/        # Embedder, Reranker, and LLM provider interfaces
│   │   ├── observability/        # OpenTelemetry & Arize Phoenix tracing setup
│   │   ├── repositories/         # Async data access layer
│   │   └── safety/               # Output safety guards (PII, evidence grounding, citations, LLM judge)
│   └── tests/
│       ├── unit/                 # Fast isolated unit tests (agents, safety, capabilities, auth)
│       ├── integration/          # pgvector and real-database integration test suite
│       └── e2e/                  # End-to-end multi-agent chat workflow test suite
│
├── frontend/                     # Next.js App Router application
│   ├── app/
│   │   ├── manager/              # Manager Portal (vacancies, applicants, leave approvals, settings, audit)
│   │   ├── employee/             # Employee Portal (leave dashboard, directory, chat assistant)
│   │   ├── candidate/            # Candidate Portal (job board, 1-click resume application, status tracking)
│   │   ├── signin/               # Role-aware authentication page
│   │   ├── search/ & ingest/     # Knowledge base inspection & manual ingestion tools
│   │   └── page.tsx              # Role-aware landing & redirect dispatcher
│   └── components/               # Shared UI elements (chat widget, navigation, dialogs, badges)
│
├── docs/                         # Architecture Decision Records (ADRs) and test reports
└── scripts/                      # Knowledge seeding & E2E smoke testing utilities
```

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/)
- *(Optional for local native run)*: [Python 3.12+](https://www.python.org/) & [`uv`](https://docs.astral.sh/uv/), [Node.js 18+](https://nodejs.org/)

---

### One-Command Docker Setup (Recommended)

Start the entire ecosystem with a single command:

```bash
make up
```

*(Alternatively, run `./run.sh`)*

This command automatically:
1. Creates `.env` from `.env.example` if not present.
2. Builds and starts **PostgreSQL (pgvector)**, **MinIO**, **Redis**, **Mailpit**, and **Arize Phoenix**.
3. Executes async **Alembic migrations**.
4. Starts the **FastAPI Backend**, **Ingestion Worker**, **Recruitment Outbox Worker**, and **Next.js Frontend**.
5. Seeds demo users, departments, vacancies, leave policies, and sample knowledge documents.

#### 🌐 Service Endpoints

| Service | URL | Description |
|---|---|---|
| 🖥️ **Frontend Portal** | [http://localhost:3000](http://localhost:3000) | Next.js Unified Role-Aware Web App |
| 📖 **Backend API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive Swagger / OpenAPI Specification |
| 📊 **Arize Phoenix** | [http://localhost:6006](http://localhost:6006) | LLM Tracing, Multi-Agent Spans & Observability |
| 📬 **Mailpit (Email)** | [http://localhost:8025](http://localhost:8025) | Development SMTP Web Inbox |
| 🗄️ **MinIO Console** | [http://localhost:9101](http://localhost:9101) | S3 Bucket Explorer (`minioadmin` / `minioadmin`) |

---

### 🔑 Demo Accounts

The database is pre-seeded with three demo personas:

| Role | Email | Password | Access Level & Landing Page |
|---|---|---|---|
| 👔 **HR Manager** | `manager@example.com` | `manager123` | Full HR Admin rights (`/manager`) |
| 👤 **Employee** | `employee@example.com` | `employee123` | Self-service leave & company directory (`/employee`) |
| 📄 **Candidate** | `candidate@example.com` | `candidate123` | Vacancy application & status tracking (`/candidate`) |

---

## 👥 Portals & User Journeys

### 👔 Manager / HR Admin Portal (`/manager`)
- **Applicant Tracking System (ATS)**: Create vacancies, inspect candidate applications, download original resumes, review AI match scores, key criteria analysis, strengths & weaknesses.
- **Hiring Decisions**: Advance candidates (`SHORTLIST`, `REJECT`) or instantly convert shortlisted applicants into employees.
- **Leave Request Management**: Review company-wide leave requests, check team out-of-office overlaps, approve or reject with one click.
- **Knowledge Base Management**: Upload new HR policies (Markdown, PDF, DOCX), monitor ingestion indexing status, trigger re-indexing.
- **Live Settings**: Configure LLM providers (Ollama / Cloud), model names, API keys, and custom resume evaluation system prompts with real-time hot-reload.
- **Audit Logs**: Filter and inspect immutable security & mutation audit records.

### 👤 Employee Portal (`/employee`)
- **Interactive HR Assistant Chatbot**: Natural-language leave requests (*"I want to take leave next Tuesday"*), policy questions (*"What is the sick leave policy?"*), and company Q&A with direct document citations.
- **Leave Dashboard**: Real-time remaining balance counters across Annual, Casual, Sick, and Unpaid leave types.
- **Request History**: View pending, approved, and rejected leave requests with cancellation capabilities.
- **Company Directory**: Search colleagues, job titles, departments, and work emails.

### 📄 Candidate Portal (`/candidate`)
- **Public Vacancy Board**: Browse open roles, requirements, and job descriptions.
- **1-Click Application**: Upload resume (PDF/DOCX) with automatic ATS validation and text extraction.
- **Status Tracker**: Track submitted applications and review interview/decision updates.

---

## 💻 Native Local Development

If you prefer to run services natively outside Docker:

### Backend Setup (with `uv`)

```bash
cd backend

# Install dependencies with dev and reranker extras
uv sync --extra dev --extra reranker

# Set up environment variables
cp ../.env.example ../.env

# Apply migrations
uv run alembic upgrade head

# Seed initial database
PYTHONPATH=src uv run python -m app.db.seed

# Run the FastAPI server with auto-reload
uv run uvicorn app.main:app --reload --port 8000
```

To run the workers in separate terminals:
```bash
# Ingestion Worker
uv run python -m app.jobs.ingestion_worker

# Recruitment Outbox Worker
uv run python -m app.jobs.worker
```

### Frontend Setup

```bash
cd frontend

# Install packages
npm install

# Run the development server
npm run dev
```

Frontend will be accessible at `http://localhost:3000`.

---

## ⚙️ Configuration & Environment Variables

Key environment variables in `.env` (refer to `.env.example` for the full annotated list):

| Category | Variable | Default | Description |
|---|---|---|---|
| **App** | `APP_ENV` | `development` | Environment mode (`development`, `production`) |
| **App** | `DEBUG` | `true` | Enable debug logging |
| **Database** | `DATABASE_URL` | `postgresql+asyncpg://hr:hr@localhost:5433/hr_assistant` | Async SQLAlchemy PostgreSQL connection string |
| **Redis** | `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for agent session storage & locks |
| **Auth** | `AUTH_PROVIDER` | `jwt` | Auth provider (currently `jwt`) |
| **Auth** | `JWT_SECRET_KEY` | *(Random Secret)* | Secret key for signing HS256 tokens |
| **Auth** | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token expiration time in minutes |
| **MinIO** | `MINIO_ENDPOINT` | `localhost:9100` | S3 API endpoint for document and resume storage |
| **MinIO** | `MINIO_BUCKET` | `hr-documents` | Object storage bucket name |
| **LLM Generation** | `LLM_ENABLED` | `true` | Enable generative LLM responses in chat |
| **LLM Generation** | `LLM_URL` | `https://ollama.com` | LLM service endpoint |
| **LLM Generation** | `LLM_MODEL` | `gpt-oss:120b-cloud` | Generation model name |
| **Knowledge/RAG** | `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model (768-dimensional) |
| **Knowledge/RAG** | `RERANKER_ENABLED` | `false` | Enable cross-encoder reranking |
| **Knowledge/RAG** | `RERANKER_MODEL` | `BAAI/bge-reranker-base` | Hugging Face cross-encoder model |
| **Knowledge/RAG** | `RETRIEVAL_TOP_K` | `15` | Candidates fetched per retrieval leg |
| **Knowledge/RAG** | `RETRIEVAL_CONFIDENCE_THRESHOLD` | `0.4` | Minimum confidence score for grounding |
| **Email** | `SMTP_HOST` / `SMTP_PORT` | `localhost` / `1025` | SMTP server connection (Mailpit) |
| **Observability** | `OTEL_ENABLED` | `true` | Enable OpenTelemetry tracing |
| **Observability** | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:6006/v1/traces` | Arize Phoenix OTLP collector URL |

---

## 📡 REST API Reference

The backend exposes a clean, modular REST API. Below is a summary of major endpoints:

### Authentication & Identity (`/api/auth`, `/api/people`)
- `POST /api/auth/login`: Authenticate with email & password; returns JWT token and user context.
- `GET /api/people/me`: Get current employee profile and department info.
- `GET /api/people/employees`: List company employees (*HR Admin*).
- `POST /api/people/employees`: Create new employee record (*HR Admin*).
- `POST /api/people/hire`: Convert an applicant to an employee (*HR Admin*).

### Multi-Agent Chat (`/api/chat`)
- `POST /api/chat`: Send a turn to the LangGraph supervisor assistant (authenticated).
- `GET /api/chat/conversations`: List user conversation history.
- `GET /api/chat/conversations/{id}/messages`: Retrieve full transcript for a conversation.
- `POST /api/chat/public`: Unauthenticated recruitment Q&A endpoint for prospective candidates.

### Knowledge & RAG (`/api/knowledge`)
- `POST /api/knowledge/documents/upload`: Upload policy document for async parsing & embedding.
- `GET /api/knowledge/documents`: List registered documents with lifecycle statuses.
- `GET /api/knowledge/jobs/{job_id}`: Inspect ingestion job status and chunk breakdown.
- `POST /api/knowledge/jobs/{job_id}/retry`: Retry a failed ingestion job.
- `GET /api/knowledge/search?q={query}`: Test hybrid retrieval (BM25 + vector + rerank).

### Leave Management (`/api/leave`)
- `GET /api/leave/balances`: Get current employee's remaining leave balances.
- `GET /api/leave/requests`: List leave requests (filtered by status/role).
- `POST /api/leave/requests`: Submit a new leave request.
- `POST /api/leave/requests/{id}/decision`: Approve or reject a leave request (*HR Admin*).
- `POST /api/leave/requests/{id}/cancel`: Cancel a pending leave request.
- `GET /api/leave/team-out-of-office`: View upcoming leave overlaps across the team.

### Recruitment & ATS (`/api/recruitment`)
- `GET /api/recruitment/vacancies`: List all job vacancies (public / filtered).
- `POST /api/recruitment/vacancies`: Create a new job vacancy (*HR Admin*).
- `POST /api/recruitment/vacancies/{id}/apply`: Apply to a vacancy by uploading a resume (PDF/DOCX).
- `GET /api/recruitment/vacancies/{id}/applications`: List candidate applications with match scores (*HR Admin*).
- `GET /api/recruitment/applications/{id}`: Detailed evaluation breakdown and structured resume (*HR Admin*).
- `POST /api/recruitment/applications/{id}/decision`: Record shortlist or reject decision (*HR Admin*).

### Settings & Audit (`/api/settings`, `/api/audit`)
- `GET /api/settings`: Retrieve current LLM connection and scoring prompt settings (*HR Admin*).
- `PUT /api/settings`: Update LLM model, API keys, or prompt overrides with live reload (*HR Admin*).
- `GET /api/audit`: Query paginated security and business mutation audit logs (*HR Admin*).

---

## 🧪 Testing & Quality Assurance

The codebase includes a comprehensive test suite across unit, integration, and E2E agent boundaries:

```bash
# Run standard unit tests (fast, in-memory)
make test

# Run pgvector integration tests (requires running database)
make test-integration

# Run the complete Leave Agent E2E multi-agent test suite (31 scenarios)
cd backend && uv run pytest tests/e2e/test_leave_chat_e2e.py -v

# Run code style & linting checks
make lint

# Run end-to-end ingestion pipeline smoke test
cd backend && uv run python ../scripts/e2e_ingestion.py
```

---

## 📊 AI Observability & Tracing

This project embeds native tracing via **Arize Phoenix** and **OpenInference**:
- Every chat turn captures full span traces: Supervisor routing decision ➔ Agent execution ➔ RAG retrieval steps ➔ LLM generation tokens.
- RAG retrieval metrics (cosine similarities, reranker scores, token latency) are visible in real-time.
- Open [http://localhost:6006](http://localhost:6006) to inspect traces, monitor multi-agent latency, and debug prompt evaluations.

---

## 📄 License

This project is licensed under the **MIT License**.
