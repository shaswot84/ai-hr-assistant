# Auth Development Plan — Sprint 2 (Recruitment module)

> Author: Nitin · Branch: `feature/auth-and-recruitment`
> Status: **Implemented · RESOLVED (2026-08-05): Keycloak → Clerk → self-issued JWT**

---

## 1. Goal (revised)

Give the backend and frontend a **robust, self-contained authentication layer** so
the Recruitment module runs against a **self-issued JWT** auth provider. Keycloak,
Clerk, and the dev-stub provider have all been **removed** — there is no external
IdP, no cloud dependency, and no webhook/tunnel. Every localhost/dev clone
authenticates identically against the same backend. Auth is still built behind the
`AuthProvider` abstraction + `UserContext`, so swapping providers later requires no
recruitment-code changes.

Decisions locked in AGENTS.md §14.2 (as revised):
- Build the module against an `AuthProvider` abstraction + `UserContext`.
- Single provider: **self-issued JWT** (`JwtAuthProvider`). `get_auth_provider`
  hard-fails unless `AUTH_PROVIDER=jwt`.
- Credentials: email + password stored on `application_user` (PBKDF2-HMAC-SHA256
  hashed, stdlib — no bcrypt/passlib dependency).
- Coarse roles: `HR_ADMIN`, `EMPLOYEE`, `CANDIDATE`. The role is **read from the
  DB on every request** (authoritative state), never trusted from the token.
  Manager/recruiter authority is derived in FastAPI from `employee.manager_employee_id`.

---

## 2. Architecture

### 2.1 Flow

```text
Next.js (role-aware portals)
   │  POST /api/auth/login {email, password}
   ▼
FastAPI auth route → JwtAuthProvider.verify_credentials()
   │  (check application_user.password_hash via constant-time compare)
   ▼
Signed HS256 JWT  (sub = application_user.external_subject, 60-min expiry)
   │  stored client-side in lib/auth.ts (localStorage + module store)
   ▼
Subsequent requests → Authorization: Bearer <JWT>
   ▼
AuthProvider interface            ← the seam (backend owns this)
   └── JwtAuthProvider.authenticate(request)
        (verify signature/exp/iss; load application_user; build UserContext)
   ▼
UserContext { subject, email, display_name, coarse_role }   ← role from DB
   ▼
FastAPI handlers + Enforcement Layer (role checks, derived manager authority)
```

- Frontend uses a custom email/password login form (`/login`). On success the token
  is stored in `lib/auth.ts`; `lib/api.ts` attaches `Authorization: Bearer` to every
  request and clears it on sign-out.
- `GET /api/auth/me` returns the resolved `UserContext`; the client routes
  `/manager` vs `/candidate` on it.
- Backend signs tokens with `JWT_SECRET_KEY` (HS256). Expiry is short (60 min); the
  coarse role is re-read from `application_user` on every request, so a role change
  takes effect immediately and a deleted user is denied immediately.

### 2.2 UserContext

Minimal, serializable shape shared by backend + frontend:

```text
UserContext {
  subject: str        # application_user.external_subject (the JWT "sub")
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

## 3. Implementation (DONE on `feature/auth-and-recruitment`)

| Area | File(s) |
|---|---|
| JWT config | `backend/src/app/config/settings.py` — `JwtSettings` (env prefix `JWT_`): `secret_key`, `algorithm`, `access_token_expire_minutes`, `issuer` |
| Provider seam | `backend/src/app/auth/provider.py` — `AuthProvider` ABC + `UserContext` |
| Password hashing | `backend/src/app/auth/passwords.py` — PBKDF2-HMAC-SHA256, constant-time verify |
| JWT provider | `backend/src/app/auth/jwt.py` — sign/verify HS256 tokens, `verify_credentials`, `login`, `authenticate` (reads role from DB) |
| Auth routes | `backend/src/app/api/routes/auth.py` — `POST /api/auth/login`, `GET /api/auth/me` |
| FastAPI wiring | `backend/src/app/api/deps.py` — `get_auth_provider` (jwt-only), `get_current_user`, `require_role` |
| Model | `backend/src/app/domain/identity.py` — `application_user.password_hash` column |
| Seed | `backend/src/app/db/seed.py` — demo users `manager@example.com`/`manager123` (HR_ADMIN) and `candidate@example.com`/`candidate123` (CANDIDATE) |
| Deleted | `auth/clerk.py`, `auth/dev_stub.py`, `auth/keycloak.py`; Clerk webhook; `infra/keycloak/`; Clerk frontend SDK |
| Frontend | `app/login/page.tsx` (email+password form), `lib/auth.ts` (token store), `lib/api.ts` (`login`/Bearer attach), `components/header.tsx` (client-side sign-out) |
| Tests | `backend/tests/unit/test_auth.py` (login, token issuance, role enforcement), `conftest.py` test-only `HeaderAuthProvider` → 11 pass |

---

## 4. JWT configuration — non-negotiables

- **`JWT_SECRET_KEY`** must be a long random string (≥32 chars) and differ between
  dev and prod. The provider refuses to start if it is empty.
- **`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`** default 60 — keep short; roles are re-read
  from the DB per request, so nothing is lost by short lifetimes.
- **Passwords**: PBKDF2-HMAC-SHA256 (600k iterations, random 16-byte salt), stored
  as `pbkdf2_sha256$<iterations>$<salt>$<hash>`. Never store plaintext.
- **Login failures**: a single generic 401 for both unknown email and wrong password
  (no user-enumeration).
- Seed credentials (dev only): `manager@example.com` / `manager123` (HR_ADMIN),
  `candidate@example.com` / `candidate123` (CANDIDATE).

Failure behavior (AGENTS.md §8): unverifiable/expired/missing token → `401`. There
is **no dev-stub** and no fallback authentication path.

---

## 5. Out of scope (this sprint)

- Employee portal (RAG + leave) — placeholder only.
- MFA, SSO/LDAP, token refresh, password reset flows — not needed for the demo.
- Fine-grained authorization engine — just the seam + coarse role checks needed by
  recruitment. Derived manager/recruiter authority lands with the recruitment module
  (plan-recruitment.md).

---

## 6. Definition of Done

- [x] `AuthProvider` seam; single `JwtAuthProvider`; `get_auth_provider` hard-fails unless `jwt`.
- [x] `POST /api/auth/login` returns a signed HS256 JWT; `GET /api/auth/me` returns `UserContext`; 401/403 as expected.
- [x] Passwords hashed (PBKDF2) and never stored in plaintext; constant-time comparison.
- [x] Roles read from the DB on every request (authoritative), not trusted from the token.
- [x] Frontend login form + Bearer attach + client-side sign-out; routes by role.
- [x] Unit tests for hashing, login, token use, and role enforcement; CI green (lint + tests).
- [x] Docs updated; author can explain every line.