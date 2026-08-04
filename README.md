# AI HR Assistant

AI-powered HR assistant for startups/SMEs: policy Q&A (RAG), leave management, and
recruitment with AI-assisted candidate evaluation.

**Current scope (Sprint 2, Week 11):** Recruitment module + swappable Auth.
See [`AGENTS.md`](../AGENTS.md) and `docs/plan-auth.md`, `docs/plan-recruitment.md`.

## Stack

- **Frontend**: Next.js 16 (React 19, Tailwind v4) — Manager + Candidate portals.
- **Backend**: FastAPI (Python), dependency management via `uv`.
- **Auth**: swappable `AuthProvider` interface — `dev_stub` (default) or Keycloak (`start-dev`).
- **Database**: PostgreSQL; **MinIO** for resumes; **Mailpit** for dev email.
- **AI scoring**: hosted Ollama API via Model Gateway; deterministic keyword fallback when no key is set.
- **Jobs**: PostgreSQL-backed transactional outbox + worker.

## Prerequisites

- Docker Desktop (or Docker + Compose) with at least ~8 GB RAM for the full stack
  (Keycloak alone needs ~1 GB JVM heap).

## Quick start

```bash
cp .env.example .env          # defaults work for local dev
docker compose up -d --build
```

This starts seven services:

| Service   | Port  | Notes                                        |
|-----------|-------|----------------------------------------------|
| frontend  | 3000  | Manager + Candidate portals                  |
| backend   | 8000  | FastAPI (reload enabled, source is live-mounted) |
| worker    | —     | Outbox consumer: evaluations + email         |
| postgres  | 5432  | HR + keycloak DBs                            |
| keycloak  | 8080  | Dev-mode Keycloak, realm auto-imported       |
| minio     | 9000/9001 | Resume object storage (API / console)     |
| mailpit   | 8025  | Dev email UI (SMTP :1025)                    |

Verify everything is healthy:

```bash
docker compose ps
curl http://localhost:8000/health      # {"status":"ok"}
```

## Using the app

1. Open **http://localhost:3000/login**.
2. Pick a persona (Candidate / Manager / Employee) and sign in with the dev stub.
3. **Manager**: create a vacancy → watch applications arrive with an AI score →
   approve (SHORTLISTED + interview email) or reject (rejection email).
4. **Candidate**: browse open vacancies → upload a resume (PDF/DOCX, ≤ 10 MB) →
   track application status.
5. Emails land in **Mailpit** at http://localhost:8025.

### Keycloak (optional)

The app runs with `AUTH_PROVIDER=dev_stub` by default so no Keycloak container is
required. To exercise the Keycloak provider:

- Admin console: http://localhost:8080/admin (admin / admin).
- Realm `hr-assistant` is auto-imported with roles `HR_ADMIN`, `EMPLOYEE`,
  `CANDIDATE` and users `manager` / `candidate` (password `password`).
- Set `AUTH_PROVIDER=keycloak` in `backend` and `worker` env (compose) and provide
  a Keycloak access token (see `backend/src/app/auth/keycloak.py`).

## AI resume scoring

- With `OLLAMA_API_KEY` set in `.env`, the worker calls the hosted Ollama API to
  score resumes vs the job title + description.
- Without a key (or on API failure), the worker falls back to a deterministic
  keyword-overlap scorer so the demo never breaks. The chosen path is recorded in
  `application_evaluation.model`.

## Running tests / lint

Backend (from `backend/`):

```bash
uv sync
PYTHONPATH=src uv run --with 'pytest>=8.0.0' pytest -q tests/unit
uv run --with ruff ruff check src/
```

Frontend (run inside the container, or locally after `npm install`):

```bash
docker compose exec frontend sh -c 'cd /app && npm run build'   # type check + build
docker compose exec frontend sh -c 'cd /app && npx eslint .'
```

## API overview (dev stub auth)

| Method | Path                                   | Role        | Purpose                       |
|--------|----------------------------------------|-------------|-------------------------------|
| POST   | `/api/auth/dev-login`                  | —           | Stub login (sets cookie)      |
| GET    | `/api/auth/me`                         | any         | Current user                  |
| GET    | `/api/vacancies`                       | any         | List vacancies (OPEN for cands) |
| POST   | `/api/vacancies`                       | `HR_ADMIN`  | Create vacancy                |
| GET    | `/api/vacancies/{id}`                  | any         | Vacancy detail                |
| POST   | `/api/vacancies/{id}/applications`     | `CANDIDATE` | Apply with resume upload      |
| GET    | `/api/vacancies/{id}/applications`     | `HR_ADMIN`  | Applications for a vacancy    |
| GET    | `/api/applications/mine`               | `CANDIDATE` | My applications               |
| GET    | `/api/applications/{id}`               | `HR_ADMIN`  | Application + evaluation      |
| POST   | `/api/applications/{id}/decision`      | `HR_ADMIN`  | approve / reject              |
| GET    | `/api/applications/{id}/resume`        | `HR_ADMIN`  | Download stored resume        |

Interactive docs: http://localhost:8000/docs

## Architecture notes

- Manager == Admin == Recruiter (single `HR_ADMIN` coarse role). Manager/recruiter
  authority is derived in the FastAPI layer, not from a Keycloak role.
- AI output is **advisory**: scores live in `application_evaluation`, never on the
  authoritative `application` row. Decisions are made by humans and recorded in
  `approval` + `outbox_job`.
- Emails go through the transactional outbox — written in the same DB transaction
  as the decision, so notifications can't be silently lost.
