# Auth Development Plan — Sprint 2 (Recruitment module)

> Author: Nitin · Branch: `feature/auth-and-recruitment`
> Status: Planning · Target: swappable auth so Keycloak can be swapped later

---

## 1. Goal

Give the backend and frontend a **swappable auth layer** so the Recruitment
module can be built, demoed, and tested **without depending on a Keycloak
container**, while keeping Keycloak a first-class provider that can be
dropped in later (or replaced entirely by another OIDC IdP) without
touching recruitment code.

Decisions locked in AGENTS.md §14.2:
- Build the module against an `AuthProvider` abstraction + `UserContext`
  from day one.
- A **dev-stub provider** is the default for local dev/CI/tests.
- **Keycloak** is one concrete provider, **dev-mode only** (`start-dev`,
  `keycloak:26.0`, plain HTTP `:8080`).
- Coarse roles: `HR_ADMIN`, `EMPLOYEE`, `CANDIDATE`. Manager/recruiter
  authority is derived in FastAPI from `employee.manager_employee_id`, not
  from a Keycloak role.

---

## 2. Architecture

### 2.1 Seam

```text
Next.js (role-aware portals)
   │  login / logout / token exchange
   ▼
AuthProvider interface            ← the seam (backend owns this)
   ├── KeycloakProvider           (OIDC code flow, JWKS validation)
   └── DevStubProvider            (mock claims / header, no infra)
   ▼
UserContext { subject, email, name, coarse_role }
   ▼
FastAPI handlers + Enforcement Layer (role checks, derived manager authority)
```

- Frontend talks to **one session endpoint** (`/api/auth/me`,
  `/api/auth/login`, `/api/auth/logout`) — never to Keycloak directly.
- The same seam is exposed client-side so Next.js can route by role
  (`/manager` vs `/candidate`).

### 2.2 UserContext

Minimal, serializable shape shared by backend + frontend:

```text
UserContext {
  subject: str        # application_user.external_subject (Keycloak `sub` / stub id)
  email: str
  display_name: str
  coarse_role: "HR_ADMIN" | "EMPLOYEE" | "CANDIDATE"
  # optional, for derived authority later:
  # employee_id / candidate_id resolved by app, not auth
}
```

Auth answers *who you are + your coarse role*. It does **not** resolve
`employee_id`, `candidate_id`, or manager relationships — that is the
Domain/Identity layer's job (see plan-recruitment.md).

---

## 3. Deliverables / Task breakdown

### Phase A — Core seam + stub (foundation)

| # | Task | Details |
|---|---|---|
| A1 | `UserContext` model | `backend/src/app/contracts/auth.py` (pydantic). Shared shape. |
| A2 | `AuthProvider` ABC | `backend/src/app/auth/provider.py` — `authenticate(request) -> UserContext`, `require_role(...)`, `build_login_url(...)`, `exchange_code(...)`, `logout(...)`. |
| A3 | `DevStubProvider` | `backend/src/app/auth/dev_stub.py` — reads role from env/header (e.g. `X-Dev-Role`, `X-Dev-User`) for local dev + tests. No container needed. |
| A4 | FastAPI dependency + router | `auth/me`, `auth/login`, `auth/logout`; `get_current_user` dependency in `backend/src/app/api/deps.py`. |
| A5 | Config | `AUTH_PROVIDER=dev_stub\|keycloak`, keys for Keycloak in `.env` (from `keycloak_docker_setup.md`). |
| A6 | Unit tests | `backend/tests/unit/auth/` — stub + interface contract, dependency injection, role rejection (403). |

### Phase B — Keycloak provider (dev mode)

| # | Task | Details |
|---|---|---|
| B1 | `KeycloakProvider` | `backend/src/app/auth/keycloak.py` — OIDC code flow + JWKS token validation via `httpx`/`python-jose` (or `authlib`), maps roles → `UserContext`. |
| B2 | Docker Compose service | `keycloak` service per `keycloak_docker_setup.md` (`start-dev`, shared Postgres `keycloak` DB, `KC_JVM_OPTS` cap, healthcheck). |
| B3 | Realm bootstrap | `infra/keycloak/realm-export.json` — realm `hr-assistant`, client `hr-portal`, roles `HR_ADMIN/EMPLOYEE/CANDIDATE`, test user. Use `--import-realm` for reproducibility. |
| B4 | Config wiring | `AUTH_PROVIDER=keycloak` path; verify `auth/me` returns `UserContext` with a real token. |
| B5 | Frontend login flow | Next.js redirect to Keycloak `/auth`, handle callback, store session, route by role. |
| B6 | Integration smoke test | Login as HR_ADMIN and CANDIDATE test users → correct portal routing. |

### Phase C — Role-aware frontend shell

| # | Task | Details |
|---|---|---|
| C1 | Session client | `lib/auth.ts` — `useSession()`, `login()`, `logout()`, role guard. |
| C2 | Role guard / layout | `app/(manager)/layout.tsx` + `app/(candidate)/layout.tsx` — middleware or layout-level redirect to `/login` or role home when unauthorized. |
| C3 | Login page | `/login` — role selection landing (employee placeholder), Keycloak redirect in prod mode / stub login in dev. |

---

## 4. Keycloak (dev-mode only) — non-negotiables

From `hr-project-docs/architecture/keycloak_docker_setup.md`:

- Image `quay.io/keycloak/keycloak:26.0`, command `["start-dev"]`.
- Reuses shared PostgreSQL (`keycloak` DB) — **not** its own server.
- Plain HTTP on `:8080` (no HTTPS/clustering/MFA).
- `KC_JVM_OPTS="-Xms512m -Xmx1g"` to cap memory.
- Roles: `HR_ADMIN`, `EMPLOYEE`, `CANDIDATE`. Do **not** create
  `MANAGER`/`RECRUITER` roles.

Failure behavior (AGENTS.md §8): Keycloak down → `401`, never fall back to
unauthenticated state. The dev-stub is for dev/CI only, not a runtime
fallback.

---

## 5. Out of scope (this sprint)

- Employee portal (RAG + leave) — placeholder only.
- MFA, SSO/LDAP, HTTPS, clustering, multi-tenant realms.
- Fine-grained authorization engine — just the seam + coarse role checks
  needed by recruitment. Derived manager/recruiter authority lands with the
  recruitment module (plan-recruitment.md).

---

## 6. Definition of Done

- [ ] `AuthProvider` seam with dev-stub + Keycloak provider both runnable.
- [ ] `auth/me|login|logout` endpoints return/accept `UserContext`.
- [ ] Role checks on recruitment endpoints (403 for wrong role).
- [ ] Keycloak dev stack boots from `docker compose up -d` with realm import.
- [ ] Login routes HR_ADMIN → `/manager`, CANDIDATE → `/candidate`.
- [ ] Unit tests for seam + stub; CI green (lint + tests).
- [ ] Docs updated; author can explain every line.
