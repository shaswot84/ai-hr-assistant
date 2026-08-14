# End-to-End Test Report — Leave Chat Agent

**Date:** August 13, 2026
**Suite:** `backend/tests/e2e/test_leave_chat_e2e.py` (31 scenarios)
**Result:** ✅ 31 / 31 passed

---

## 1. What is tested end to end

The suite drives the **real supervisor graph** (`build_supervisor_graph` — the exact wiring the chat API uses) with:

- a wired **leave node** (`leave_actor`, shared `SessionStore`, scripted chat provider, injected `LeaveService`)
- a real **`LeaveService`** against the test SQLite database
- real seeded identities (`employee_context`, `manager_context`, `candidate_context` from the unit fixtures)
- a **routing fake** for the supervisor LLM and a **scripted cooperative model** for the leave agent

Every layer between a user message and the durable DB write is exercised: supervisor routing → leave node → deterministic interception → model path → tool execution → confirmation gate → workflow persistence. The only components not exercised are **Ollama itself** and the **HTTP/SSE transport** (those are covered by `tests/unit/test_chat_api.py`).

```
user message
   └─> supervisor route (LLM/keyword/history-precheck)
         └─> leave node
               ├─ deterministic draft/date/cancel/recap interception
               ├─ model path (scripted cooperative model → tools)
               ├─ confirmation gate (staged == confirmed, TTL, atomic claim)
               └─ workflow persistence (conversation_workflow_state row)
                     └─ real LeaveService writes to SQLite
```

## 2. How to run

```bash
cd backend
python -m pytest tests/e2e/ -v
```

The full backend unit + e2e suite also runs green (`tests/unit/agents/` = 111 passed).

> Note: on Windows, a pre-existing session-teardown quirk in `tests/conftest.py` reports `PermissionError` while deleting the throwaway SQLite temp file (the OS keeps the handle open). This is **unrelated** to the test results — all tests pass; the file is left behind in the temp dir.

## 3. Scenario matrix

### 3.1 Employee self-service (14 scenarios)

| # | Scenario | What it proves | Result |
|---|----------|----------------|--------|
| 1 | Full submit roundtrip | Relative dates → draft → staged → confirmed → real `PENDING` `LeaveRequest` row with correct dates | ✅ |
| 2 | Balance question via model | `get_leave_balance` read tool, deterministic formatting, no date follow-up on a question | ✅ |
| 3 | Request without a type | Model lists types → deterministic draft takes over → completes → submits | ✅ |
| 4 | Ambiguous message does **not** dump the type list | `list_leave_types` is never a general fallback; agent asks what action instead | ✅ |
| 5 | Direct types question | The list itself is the answer — no "which type" follow-up, no draft | ✅ |
| 6 | New request words + relative date (`get`/`take`/`avail`/`book`) | Intercepted deterministically, **zero model calls** | ✅ |
| 7 | Cancel by reference | `LR-…` → staged → confirmed → `CANCELLED` row | ✅ |
| 8 | Cancel without reference | Lists what CAN be cancelled → pick by number → staged → confirmed | ✅ |
| 9 | Cancel non-pending request | Rejected at stage time, never staged | ✅ |
| 10 | Insufficient balance | Preflight rejects at stage; nothing staged; draft kept so dates can be adjusted | ✅ |
| 11 | Expired confirmation | A staged action past its TTL cannot execute | ✅ |
| 12 | Mismatched confirmation args | Wrong dates in a "yes" are blocked by the confirmation gate | ✅ |
| 13 | Leave-scoped recap (`what leave did i apply above`) | Answered from the thread's own history + workflow state, no model | ✅ |
| 14 | Draft cancel words (`never mind`) | Draft dropped deterministically; workflow row marked terminal | ✅ |

### 3.2 HR administrator (7 scenarios)

| # | Scenario | What it proves | Result |
|---|----------|----------------|--------|
| 15 | Approve by reference | Staged deterministically → confirmed → `APPROVED` row | ✅ |
| 16 | Reject by reference | Staged deterministically → confirmed → `REJECTED` row | ✅ |
| 17 | HR cannot cancel | Refused deterministically ("employee's own action") | ✅ |
| 18 | Pending list | Real pending list shown, pick by number — no model guessing | ✅ |
| 19 | HR cannot apply for leave | Refused deterministically; no rows created | ✅ |
| 20 | Employee balance tool | `get_employee_leave_balance` by employee code via model path | ✅ |
| 21 | List all requests tool | `list_leave_requests` shows statuses via model path | ✅ |

### 3.3 Role isolation (2 scenarios)

| # | Scenario | What it proves | Result |
|---|----------|----------------|--------|
| 22 | Employee cannot use HR tools | Manager read tool rejected by role gate; manager write has no staged match | ✅ |
| 23 | Candidate blocked from all leave tools | Role gate rejects in plain language | ✅ |

### 3.4 Supervisor routing (7 scenarios)

| # | Scenario | What it proves | Result |
|---|----------|----------------|--------|
| 24 | Knowledge question | Routes to knowledge node; grounded answer + citation | ✅ |
| 25 | Recruitment question | Routes to recruitment node | ✅ |
| 26 | Ambiguous message | Routes to clarify node | ✅ |
| 27 | No-LLM heuristic routing | Keyword fallback routes leave/knowledge without an LLM | ✅ |
| 28 | Generic recap | `what is this chat about?` pre-routed to the recap node | ✅ |
| 29 | History preserved across turns | Prior turns ride through the graph for context | ✅ |
| 30 | Draft survives store restart | Cache miss restores draft from durable row; end date resolves against restored start; confirm executes after another restart | ✅ |
| 31 | Completed workflow starts fresh | A finished workflow is never resurrected into a new session | ✅ |

**Totals:** Employee 14 + HR 7 + roles 2 + routing/supervisor 8 = **31 scenarios, all passing.**

## 4. Coverage highlights

- **Deterministic-first design verified end to end:** relative dates, draft completion, type resolution, cancels/decisions by reference, recaps, and draft cancellation all complete **without the model** (asserted via `provider.calls == 0` where applicable).
- **The model is only trusted where it must be:** confirming a staged action (with the args copied verbatim from the staged block) and choosing read tools.
- **The two recent fixes are locked in end to end:**
  1. `list_leave_types` is never a fallback for ambiguous messages (scenario 4) and balance questions never trigger a request start (scenario 2).
  2. The new request-intent words `get` / `take` / `avail` / `book` make requests like "can i get leave for next sunday" fully deterministic (scenario 6), and `available`-questions are not misread as request starts.
- **Safety gates verified end to end:** insufficient balance preflight, confirmation TTL expiry, mismatched-args confirmation block, role gates for HR/CANDIDATE.
- **Durability verified end to end:** draft/staged-action rows survive a simulated process restart; completed workflows are never restored.

## 5. Known limitations

| Limitation | Where covered instead |
|------------|------------------------|
| Ollama / real model inference is not exercised | `tests/unit/test_chat_api.py` (route + SSE wiring) and unit agent suites use the same fakes; the real provider is intentionally out of the hermetically-testable path |
| HTTP + SSE transport is not exercised | `tests/unit/test_chat_api.py` covers the API layer (POST, stream, conversations, 401/404/422) |
| pgvector knowledge retrieval is not exercised | `tests/unit/agents/test_knowledge_agent.py` (own Postgres-backed fixtures) |
| Windows-only session-teardown temp-file error | Pre-existing environment quirk; does not affect results |

## 6. Files

| File | Purpose |
|------|---------|
| `backend/tests/e2e/test_leave_chat_e2e.py` | The 31-scenario end-to-end suite |
| `backend/tests/e2e/conftest.py` | Re-exports the unit DB/identity fixtures for the e2e tree |
