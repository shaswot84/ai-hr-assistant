# Recruitment Development Plan — Sprint 2

> Author: Nitin · Branch: `feature/auth-and-recruitment`
> Status: Planning · Scope: Manager + Candidate recruitment workflows

---

## 1. Goal

Build the **Recruitment module** (Manager vacancy posting → Candidate
apply → AI resume evaluation → Manager approve/shortlist or reject) on top
of the swappable `AuthProvider` seam (plan-auth.md). Full end-to-end flow
runs against the dev-stub auth in local dev; Keycloak provider is
interchangeable behind the same interface.

Locked decisions (AGENTS.md §14.1):
- Candidate applies by uploading **only a resume** (PDF/DOCX).
- Resume stored in **MinIO** (`application.cv_object_key`).
- AI scores resume vs job title + description via **Ollama hosted API**
  (key in `.env` via Model Gateway).
- Result (score + overview) persisted in a **separate `application_evaluation`
  table** (not columns on `application`).
- Manager **Approve → `SHORTLISTED`** + generic interview-notification email.
  Manager **Decline → `REJECTED`** + rejection email.
- **No interview creation in scope.** SHORTLISTED email says "you'll be
  further notified about interview scheduling."
- Emails ride the **outbox** (transactional).

---

## 2. Data model (delta on Database_Implementation.md §6)

Existing (already in docs): `candidate` (§3.6), `vacancy` (§6.1),
`application` (§6.2), `interview` (§6.3 — NOT used this sprint),
`outbox_job` (§7.1, with `SEND_INTERVIEW_INVITATION` / rejection job types).

### New: `application_evaluation` (advisory AI output)

| Column | Type | Notes |
|---|---|---|
| `application_evaluation_id` | UUID | PK |
| `application_id` | UUID | FK → `application.application_id`, NOT NULL |
| `score` | INT | 0–100, advisory |
| `overview` | TEXT | AI summary for the manager |
| `raw_payload` | JSONB | full AI JSON evidence (defensive, reprocessable) |
| `model` | VARCHAR(100) | Ollama model used |
| `prompt_version` | VARCHAR(50) | prompt tag |
| `token_usage` | JSONB | prompt/completion tokens (optional) |
| `latency_ms` | INT | inference latency (optional) |
| `evaluated_at` | TIMESTAMPTZ | default now() |

- One-to-many so a resume can be **re-evaluated** (new model) without
  touching `application` state.
- `application.application_status` stays authoritative: `APPLIED →
  SHORTLISTED | REJECTED`.
- Alembic migration adds this table (and any recruitment tables not yet
  created).

---

## 3. Backend tasks

### Phase A — Domain + repos (no AI yet)

| # | Task | Details |
|---|---|---|
| A1 | Recruitment domain models | `backend/src/app/domain/recruitment.py` (SQLAlchemy): `candidate`, `vacancy`, `application`, `application_evaluation`. |
| A2 | Repositories | `backend/src/app/repositories/recruitment.py` — create/list/update queries (vacancy by owner, application by candidate+role). |
| A3 | Alembic migration | Add recruitment tables + `application_evaluation` to the migrations dir. |
| A4 | Vacancy capabilities | `backend/src/app/capabilities/recruitment.py` — `create_vacancy`, `list_vacancies(manager)`, `get_vacancy`, `close_vacancy`. |
| A5 | Application capabilities | `apply_to_vacancy(candidate, vacancy, resume_object_key)`, `list_my_applications(candidate)`, `get_application_for_review(manager, application_id)`, `decide_application(manager, application_id, approve|reject)`. |
| A6 | Auth wiring | All endpoints take `UserContext`; role/identity checks (manager owns vacancy; candidate sees own applications). |

### Phase B — Resume intake + MinIO

| # | Task | Details |
|---|---|---|
| B1 | Resume upload endpoint | `POST /applications` — multipart resume only; validate PDF/DOCX, size (≤10MB), not empty. |
| B2 | MinIO object store | `backend/src/app/integrations/object_store.py` — upload bytes, return `cv_object_key`; reuse `ObjectStore` abstraction pattern from `feature/ingestion`. |
| B3 | Transactional create | Create `application` (APPLIED) + upload to MinIO; if MinIO fails → clear error, no application row (AGENTS.md §8). |
| B4 | Outbox enqueue | On create, enqueue `EVALUATE_APPLICATION` job (payload: application_id, object_key). |

### Phase C — AI evaluation (Ollama)

| # | Task | Details |
|---|---|---|
| C1 | Resume text extraction | Port `~/projects/resume/backend/extraction.py` (pdfplumber + python-docx) into `backend/src/app/knowledge/` or `integrations/` — reuse patterns only, no full lift. |
| C2 | Ollama provider via Model Gateway | `backend/src/app/model_gateway/` — add hosted Ollama chat provider (`OLLAMA_API_KEY`, base URL, model), score resume vs job title+description. |
| C3 | Scoring prompt | System + user prompt requesting JSON `{ score, overview }`; defensive parse (strip fences, clamp 0–100, fallback). Reuse reviewer.py parsing patterns. |
| C4 | Worker | `backend/src/app/jobs/` — `EVALUATE_APPLICATION` worker: pull object → extract → call Ollama → write `application_evaluation` row → mark job done. Retry w/ backoff (up to 3), graceful fallback on LLM failure (§8). |
| C5 | Re-evaluation | Optional endpoint `POST /applications/{id}/reevaluate` (provenance from new model). |

### Phase D — Manager decision + notifications

| # | Task | Details |
|---|---|---|
| D1 | Approve/Reject endpoint | `POST /applications/{id}/decision` body `{ action: approve|reject }`. TRANSACTIONAL: update status + enqueue email outbox (same transaction). |
| D2 | Email outbox jobs | Job types `SEND_INTERVIEW_INVITATION` (approve) + `SEND_APPLICATION_REJECTED` (reject); payload → email adapter. |
| D3 | Email provider (dev) | `backend/src/app/integrations/email/` — `EmailProvider` interface; **Mailpit SMTP provider** (localhost:1025). Commit state before send; retries up to 3 (§8). |
| D4 | Audit | Audit-log approve/reject/evaluate actions (actor, target, prev/new status). |

### Phase E — Progress/status read APIs

| # | Task | Details |
|---|---|---|
| E1 | Application status message | `application_status` → human text (SHORTLISTED: "further notified about scheduling", REJECTED: rejection message). |
| E2 | Evaluation status | Expose whether evaluation is done/pending so candidate portal shows "evaluating". |

---

## 4. Frontend tasks (Next.js)

### Manager portal

| # | Task | Details |
|---|---|---|
| M1 | Manager layout + guard | `app/(manager)/layout.tsx` — HR_ADMIN only. |
| M2 | Dashboard | `/manager` — stats + recent applications + "Post vacancy" CTA. |
| M3 | Vacancies list | `/manager/vacancies` — list, status filter, search. |
| M4 | Create vacancy | `/manager/vacancies/new` — form (title, dept, description, employment_type, dates) → POST. |
| M5 | Vacancy detail | `/manager/vacancies/:id` — vacancy + applications w/ status + AI score. |
| M6 | Application review | `/manager/vacancies/:id/applications/:appId` — resume (download), AI score + overview, Approve/Reject buttons. |

### Candidate portal

| # | Task | Details |
|---|---|---|
| C1 | Candidate layout + guard | `app/(candidate)/layout.tsx` — CANDIDATE only. |
| C2 | Browse vacancies | `/candidate` — OPEN vacancies list. |
| C3 | Vacancy detail | `/candidate/vacancies/:id` — job info + Apply. |
| C4 | Apply | `/candidate/vacancies/:id/apply` — resume upload (PDF/DOCX validated). |
| C5 | My applications | `/candidate/applications` — my apps + status. |
| C6 | Application detail | `/candidate/applications/:id` — status message (further-notified / rejected / evaluating). |

---

## 5. Reference: `~/projects/resume`

Reuse **patterns only** (do not full-lift):
- `extraction.py` — PDF (pdfplumber) + DOCX (python-docx) text extraction,
  graceful degradation, `_normalize`.
- `reviewer.py` — prompt building, strict-JSON request, defensive
  parsing/`_normalize_review`, retries with backoff.
- Difference: theirs reviews resume *quality* via OpenRouter; ours is a
  *hiring decision* (score vs a specific job) via the Model Gateway's
  Ollama provider. No OpenRouter dependency.

---

## 6. Out of scope (this sprint)

- Interview creation/scheduling/calendar.
- Candidate registration/profile (assuming provisioned accounts).
- Vacancy approval gate (`PENDING_APPROVAL`) — post is direct for now
  (can revisit; see hang on `approval`/`human_task`).
- Hiring conversion (candidate → employee).
- Payroll, benefits, performance, multi-tenant.

---

## 7. Definition of Done

- [ ] End-to-end: manager posts vacancy → candidate applies (resume) →
      AI scores → manager approves (SHORTLISTED + email) or rejects
      (REJECTED + email).
- [ ] Resume persisted in MinIO; `application_evaluation` populated; status
      transitions correct.
- [ ] Emails via outbox → Mailpit; verify in Mailpit UI (:8025).
- [ ] Role gating: managers see only their vacancies; candidates only their
      applications; 403 on cross-role access.
- [ ] Alembic migrations run clean; unit tests for domain/repo/evaluation/
      decision logic; CI green.
- [ ] Author can explain every line at final eval.