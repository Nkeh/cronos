# Day 4 summary

## What was built
API keys (create/list/revoke, scoped, bearer-authenticated, rate-limited), the `PLANS` seam
(`launch` plan limits + `check_limit`/`check_interval_minimum` + a tested-but-unwired downgrade
function), a save-time URL/SSRF policy module, and the full monitor CRUD API — the first
user-facing resource the app can create. `current_principal` (Day 3's pre-built seam) now branches
on `Authorization`: present means API-key-only auth, with no fallback to the cookie on any failure.
`check_limit` deliberately is **not** a FastAPI dependency — a dependency's effects (the account
row lock) would stay open across whatever the route body awaits afterward, which for monitor
creation includes the SSRF module's DNS lookup. Every creating route therefore runs all validation
first, then enters one short lock → count → insert → commit block with no non-DB await inside it.

Two real bugs were found and fixed before/during verification (see Deviations): a FOR UPDATE lock
that would have silently never been acquired on the happy path, and a backwards "newest first"
sort in the downgrade function. Both are detailed below since they're the kind of thing worth
remembering, not just fixing quietly.

**Follow-up round** (before the commit, requested after reviewing this file): the FOR UPDATE fix
above was caller-side (the create-monitor route avoided populating the identity map before
locking) — `get_account_for_update` itself is now hardened directly
(`populate_existing=True`), so the lock can't be skipped no matter what a *future* caller does
first. A dedicated test proves the lock is real (a second connection's `FOR UPDATE NOWAIT` on the
same row raises), including the exact "account already loaded" shape of the original bug. Both
concurrency races (monitor creation, API-key creation) were additionally re-run live via API-key
Bearer auth, not just session cookies.

## Files changed (grouped by area)
- **New API-key package**: `backend/app/auth/api_keys.py` (scope vocabulary, `generate_api_key`,
  `parse_bearer_token`, `authenticate` — resolves the principal via `created_by_user_id`, never
  via "the account's user"; the per-key rate limit lives *inside* `authenticate`, not per-router),
  `backend/app/auth/api_keys_router.py` (3 endpoints, prefix-collision retry via `SAVEPOINT`).
- **New `backend/app/plans/`**: `config.py` (`PlanLimits`, `PLANS`, `validate_plans_config` run at
  import time), `dependencies.py` (`check_limit`/`check_interval_minimum`/`get_account_for_update`
  — plain functions, never `Depends()`; `get_account_for_update` is the *only* place in the
  codebase that takes a row lock, by design, and always issues a real `SELECT ... FOR UPDATE` via
  `populate_existing=True`, regardless of whether the account was already loaded into the session),
  `downgrade.py` (`apply_plan_limits`/`DowngradeReport`).
- **New `backend/app/engine/ssrf_policy.py`**: pure functions (`normalize_and_validate_url`,
  `check_dns_resolves_public`) shared with Day 7's connect-time guard later.
- **New monitor CRUD**: `backend/app/monitors/router.py` + `schemas.py` — 8 endpoints, PATCH's
  target-change reset split by what it affects (failures/ewma reset unconditionally; `status`
  alone follows the pause rule), jitter/re-jitter via bound-parameter `make_interval(...)`.
- **New `backend/app/accounts/router.py` + `schemas.py`**: `GET /api/v1/usage`.
- **New `backend/app/core/openapi.py`**: documents `cookieAuth`+`bearerAuth` in `/api/docs`.
- **Modified auth**: `models.py` (`ApiKey.name`/`created_by_user_id`), `dependencies.py`
  (rewritten — the `Authorization` branch, plus a Day-3 f-string-SQL fix: `_bump_last_seen` and
  the idle-TTL check now use `make_interval(...)` with real bound parameters, not an interpolated
  string), `schemas.py` (+`ApiKeyCreateRequest`/`ApiKeyPublic`/`ApiKeyCreateResponse`).
- **Modified core**: `config.py` (+`rate_limit_api_key_max`/`_window_seconds`,
  +`ssrf_allow_hosts_set` property mirroring `trusted_proxy_ips_set`), `main.py` (wires the three
  new routers + `custom_openapi`).
- **Dependency**: `idna==3.20` promoted from transitive (via `httpx`) to direct in
  `backend/pyproject.toml`, so save-time IDNA normalization provably matches what httpx will
  connect to later; `uv lock` re-run (no new resolution needed — already in the lock transitively
  at the same version).
- **Tests**: `tests/conftest.py` (+`csrf_headers`, hoisted from `tests/auth/conftest.py` since
  `tests/api_keys/` and `tests/monitors/` need it too), `tests/helpers.py` (+`name` default in
  `make_api_key`, +`login_as` — sets a session cookie directly via `make_valid_session`, bypassing
  the real login flow for route tests), and six new test packages: `tests/api_keys/` (`test_crud`,
  `test_auth`, `test_rate_limit`), `tests/plans/` (`test_config`, `test_downgrade`),
  `tests/engine/test_ssrf_policy.py`, `tests/monitors/` (+`test_crud`, `test_patch`,
  `test_pause_resume`, `test_plan_limits`), `tests/accounts/test_usage.py`, and (follow-up)
  `tests/plans/test_locking.py` — proves `get_account_for_update`'s lock against a genuinely
  independent second connection, not just against the count-based plan-limit assertions.

## Migrations
**0007 (api key metadata)**: adds `api_keys.name` (`text`, `NOT NULL`, `CHECK length BETWEEN 1 AND
60`, nullable→backfilled→`NOT NULL` so it's safe over existing rows) and `api_keys.created_by_user_id`
(`uuid`, `FK users.id ON DELETE SET NULL`). Neither column is in SRS Section 5 — see Deviations.

## Tests: 140 -> 209 (208 run by default + 1 migration-marked)
Day 3 ended at 139 default + 1 = 140. Day 4 adds 67 new tests across six packages (206 default + 1),
then the follow-up round adds 2 more (`tests/plans/test_locking.py`), landing at **208 run by
default + 1 migration-marked = 209 total**. No decrease. The default suite was run three times in
the main round (once before, once immediately after, once again after the destructive migration
round trip wiped the test DB clean) with identical results, then once more after the hardening
follow-up — 208 passed every time. Frontend Vitest unchanged at 3.

## Live verification (commands + real output, via Caddy on :8080)
All 11 acceptance criteria run against the actual running stack (`docker compose up -d --build`,
real Mailpit for verification emails, real `psql`):
1. **Key shown once, listed without the hash**: created a key with `monitors:read`+`monitors:write`
   → `201` with `"key":"cronos_c16d1acd_QU8x..."`; `GET /api-keys` → the same row, no `key`/`key_hash`
   field present at all.
2. **Bearer, no CSRF header**: `GET /monitors` → `200 []`; `POST /monitors` → `201`. A
   `monitors:read`-only key on `POST` → `403 insufficient_scope`. Revoking the key then reusing it
   → `401 invalid_api_key`. A garbage `Bearer` header plus a *valid* session cookie on the same
   request → `401 invalid_api_key` (confirmed no fallback to the cookie).
3. **An API key calling `POST /api-keys`** → `403 session_required`.
4. **Plan limits**: filled an account to 15 monitors (all `201`), the 16th → `422 plan_limit`
   (`"The launch plan allows up to 15 monitors."`); `interval_seconds:60` →
   `422 plan_limit` with `field:"interval_seconds"` (`"The launch plan's minimum interval is 120s."`).
5. **SSRF table**, all against the live stack with real DNS: `127.0.0.1`, `[::ffff:127.0.0.1]`,
   `169.254.169.254/latest/meta-data`, `localhost:8000` → `422 url_host_blocked`;
   `user:pass@example.com` → `422 url_credentials`; `example.com:22` → `422 url_port_blocked`;
   `ftp://example.com` → `422 url_scheme`; `localtest.me` (a real public DNS name resolving to
   `127.0.0.1`) → `422 url_resolves_private`. Accepted (confirmed with a clean `201`, freeing a
   slot first): `https://example.com` and, dev-only, `http://chaos:8000/...`.
6. **Cross-account 404**: a second user's `GET` on the first user's monitor id → `404 not_found`
   (never `403`).
7. **PATCH→GET round trip**: `PATCH .../url` → `200` with the new url and `"status":"new"`; `GET`
   confirms it persisted. Then pause → `status":"paused","is_active":false`; resume →
   `"status":"new","is_active":true`. `psql`: `SELECT id, status, is_active FROM monitors WHERE
   id = '...'` → `new | t`, matching the API response exactly.
8. **Unverified user**: `POST /monitors` → `403 email_not_verified`.
9. **20 parallel creates at 10 existing**: fired as real concurrent `curl` background processes
   (not just the pytest `asyncio.gather` simulation) against the live stack — `success=5
   rejected=15`, `GET /usage` → `"monitors": 15`. Confirms the `FOR UPDATE` lock serializes real
   concurrent HTTP requests, not just async-task-scheduling order inside one process.
9a. **Follow-up — the same race via API-key Bearer auth**, not a session cookie: 10 monitors
    created via `Authorization: Bearer ...`, then 20 parallel Bearer-authenticated creates →
    `success=5 rejected=15`, `GET /usage` (Bearer) → `"monitors": 15`. Same lock, same result,
    proving it's not session-path-specific.
9b. **Follow-up — API-key creation race**: an account with 5 existing (non-revoked) keys, then 15
    parallel `POST /api-keys` (session-authenticated — API keys can't manage keys) →
    `success=5 rejected=10`; final `GET /usage` → `"api_keys": 10`, exactly at `max_api_keys`.
    Confirms `get_account_for_update`/`check_limit` serialize the api_keys resource the same way.
10. `/api/openapi.json` → `components.securitySchemes` shows both `cookieAuth` and `bearerAuth`.
    `alembic current` → `0007 (head)`; `alembic check` → `No new upgrade operations detected.`;
    `pytest -q -m migration` (the destructive downgrade-base→upgrade-head round trip) → `1 passed`.
11. Test counts above; Vitest run live → `3 passed`; `grep -rlI $'\r' backend/app backend/alembic
    backend/tests docs/progress` → no output (no CRLF). This file written before presenting the
    summary. No state-changing git command was run during the session.

## Deviations from SRS / CLAUDE.md
- `api_key.name`, `created_by_user_id`, `max_api_keys` (10), the scope vocabulary
  (`<resource>:<read|write>`), the `cronos_<prefix>_<secret>` key format, and the per-key rate
  limit are all absent from SRS Section 5/12/13 — this day's own additions, exactly as flagged in
  the approved plan.
- SRS Section 12's own "downgrade rule" text is written for the v1→v2 `launch`→`free` transition
  and is explicitly labeled "planned, not built." `apply_plan_limits` is nonetheless implemented
  and tested now per CLAUDE.md, wired to no endpoint — consistent, not a conflict.
- API-key auth resolves the principal via `api_keys.created_by_user_id` (a creator-deleted or
  orphaned key is `401`, never falls back to "the account's user").
- `PLANS`'s allowed plan-name set and the DB's `accounts.plan CHECK (plan IN ('launch'))` are two
  independently maintained lists (no DB access at Python import time to derive one from the other).
- `idna` added as a new direct dependency (was already transitive via `httpx`) so save-time
  IDNA normalization provably agrees with what httpx will connect to at probe time (Day 7).
- `apply_plan_limits` reuses monitors' `min_interval_seconds` for heartbeats too (no separate
  field exists in `PLANS`); its status-page "unpublish" step generates a fresh
  `access_token_hash` for any page that doesn't already have one, since the DB's
  `access_token_required` CHECK requires a private page to have one — the raw token itself isn't
  surfaced anywhere, since nothing calls this function in v1.
- **Two real bugs found during this day's own verification, not from an external report**:
  1. `monitors/router.py`'s `create_monitor` originally read the account's plan via
     `db.get(Account, user.account_id)` *before* the later `db.get(Account, ..., with_for_update=
     True)` in the locked block. SQLAlchemy's identity map returns a cached object on a second
     `get()` for the same primary key **without re-querying**, so the `FOR UPDATE` lock would
     never actually have been acquired — silently defeating the whole point of amendment #2 in the
     approved plan. Caught via static review (confirmed via the local `uv`-managed venv, no Docker
     needed) before any test ran; fixed by reading just the plan column via a scalar `select`
     instead, which never touches the identity map. **Proved fixed live**: 20 real concurrent
     `curl` requests against the running stack landed at exactly 15 monitors (see criterion 9).
     **Follow-up hardening**: that fix was caller-side — it made *this one* caller safe, but left
     `get_account_for_update` itself still capable of silently skipping the lock for any future
     caller that happens to load the account first. `get_account_for_update` now takes
     `populate_existing=True` alongside `with_for_update=True`, forcing a genuine re-query (and
     therefore a genuine lock) unconditionally; `tests/plans/test_locking.py` proves this directly
     — a second, fully independent connection's `SELECT ... FOR UPDATE NOWAIT` on the same account
     row raises (asyncpg's `LockNotAvailableError`, surfaced as a `DBAPIError`) while the lock is
     held, in both the plain case and the exact "account preloaded first" shape of the original
     bug. A grep audit confirms `get_account_for_update` is the only `with_for_update` site in the
     codebase, and both callers (`monitors/router.py`, `api_keys_router.py`) already route through
     it.
  2. `app/plans/downgrade.py`'s `_pause_surplus`/`_unpublish_surplus` sorted `DESC` by
     `created_at` and sliced `rows[max_count:]` — on a descending list that slice is the *oldest*
     rows, not the newest, exactly backwards from "pause the newest first." Caught by
     `tests/plans/test_downgrade.py` failing on a direct id-set comparison; fixed by sorting
     ascending instead (oldest-first; the slice after `max_count` is then correctly the newest
     surplus).

## Known issues / follow-ups
- The SSRF policy's *sync* structural check doesn't itself special-case decimal/octal-encoded IP
  literals (e.g. `0177.0.0.1`) — a hostname shaped like that falls through to the async
  DNS-resolution check instead of being caught immediately. In practice this still gets blocked
  (OS resolvers generally recognize numeric-looking hosts via `inet_aton`-style parsing before any
  real lookup), but it's not explicitly exercised by a Day 4 test — CLAUDE.md's SSRF test list
  names this form for the Day 7 connect-time guard, which is authoritative anyway per SRS Section
  13 ("save-time validation is UX only").
- `TODO (Day 8)` left in `monitors/router.py`'s `pause_monitor`: what pausing does to an open
  incident — unchanged from the approved plan, not newly discovered.
- Heartbeats' plan-limit minimum interval and the status-page unpublish token-generation gap above
  are both flagged for Day 10/Day 11 to revisit, not blocking anything today.

## Commit block

```bash
git add -A
git commit -m "day 4: API keys, PLANS + limits, monitor CRUD API with save-time SSRF checks" -m "- API keys: GET/POST /api/v1/api-keys, DELETE /{id}; format cronos_<8-hex>_<secret>, sha256 key_hash, prefix-collision retry via SAVEPOINT; scoped (<resource>:<read|write>, write implies read); bearer auth resolves the principal via created_by_user_id only, never 'the account's user' — an orphaned/creator-deleted key is 401; per-key rate limit (600/min) enforced inside authenticate() itself so it covers every router, not attached per-route
- current_principal now branches on Authorization: present means API-key-only auth, 401 on any failure, never falling back to the session cookie (the Day 3 placeholder this was built around)
- PLANS seam (app/plans/): launch-only PlanLimits dataclass validated at import time (typo'd plan name fails at process startup); check_limit/check_interval_minimum are plain functions, deliberately never a FastAPI Depends() — a dependency's account row lock would stay held across the SSRF module's DNS lookup otherwise; apply_plan_limits (the SRS downgrade rule) implemented and tested, wired to no endpoint per CLAUDE.md
- get_account_for_update hardened with populate_existing=True so it always issues a real SELECT ... FOR UPDATE regardless of whether the account was already loaded into the session's identity map — it's the only row-lock site in the codebase (grep-audited), and both callers already route through it; tests/plans/test_locking.py proves the lock against a genuinely independent second connection (FOR UPDATE NOWAIT raises LockNotAvailable), including the exact 'preloaded' shape of the bug this closes
- Save-time SSRF/URL policy (app/engine/ssrf_policy.py): scheme/credential/port/host-identity checks plus an async DNS-resolution check (NXDOMAIN/timeout fail open — DNS hiccups must not block users); idna-based IDNA2008/UTS46 normalization (promoted to a direct dependency, pinned 3.20); the dev-only SSRF_ALLOW_HOSTS escape hatch skips host-identity checks but never scheme/credentials/port
- Monitor CRUD (/api/v1/monitors): full CRUD + check-now/pause/resume; every creating/limited route runs all validation (schema, the full SSRF sequence) first, then one short lock -> count -> insert -> commit block with no non-DB await inside it; PATCH's target-change reset splits consecutive_failures/ewma (always clear) from status (follows the pause rule, required by the real paused_matches_active CHECK); jitter and re-jitter use a bound-parameter make_interval(...), never an f-string
- Fixed two real bugs found during this day's own verification: the FOR UPDATE lock above (caught via static review, then hardened at the helper level and proven both by a dedicated lock test and by live concurrent races via session AND API-key auth landing at exactly the plan limit), and a backwards newest-first sort in apply_plan_limits (caught by a direct test assertion)
- Also fixed, while touching current_principal: Day 3's two f-string-interpolated SQL intervals (_bump_last_seen, the idle-TTL check) now use make_interval(...) with real bound parameters
- GET /api/v1/usage: plan, limits, live counts (api_keys excludes revoked), launch_period notice
- /api/docs now documents both cookieAuth and bearerAuth security schemes
- Migration 0007: api_keys.name (NOT NULL, 1-60 chars) and created_by_user_id (FK users, ON DELETE SET NULL) -- both absent from SRS Section 5, flagged as Day 4 additions
- 140 -> 209 backend tests (208 run by default + 1 migration-marked), stable across every run incl. one after the destructive migration round trip; Vitest unchanged at 3
- docs/progress/day-04.md added with full live-verification output (curl against the running stack incl. two real concurrent races per resource — monitors via session AND Bearer, api_keys via session — Mailpit, a psql row check, and a direct second-connection lock proof) and every deviation"
```
