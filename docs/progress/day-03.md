# Day 3 summary

## What was built
A complete auth backend: signup, email verification, login, logout, password reset, and `GET /me`,
all under `/api/v1/auth`, backed by cookie sessions and CSRF double-submit protection, with
fail-open rate limiting through Redis and transactional email via Mailpit. Four integration gaps
in the Day 1/2 plumbing were filled along the way: a real per-request DB-session dependency (none
existed), a way to attach a specific error `code`/`field` to a hand-raised exception (`ApiError`,
the old system had one fixed code per HTTP status), rate-limit primitives and a breaker on
`FailOpenRedis` (it only had `ping`/`close`), and the `Clock` abstraction actually wired into the
app (it existed but nothing used it).

The planned per-email login rate limit was replaced mid-plan, before any code was written, because
it was a lockout vector: an attacker who knows a victim's email could lock them out from their own
IP. The shipped design counts *failures only*, split into a tight `(email, IP)` ceiling (5/15min,
reset on that pair's next success) and a looser per-email/all-IPs ceiling (30/hour, not reset by
any single success) — proven by a test where the victim logs in successfully from their own IP
while an attacker's IP is throttled on the same email.

## Files changed (grouped by area)
- **New auth package** (`backend/app/auth/`): `constants.py` (cookie/header names), `schemas.py`
  (every request/response model), `security.py` (password hashing, token hashing, the password
  policy, the dummy hash, `common_passwords.txt`), `rate_limit.py` (client-IP resolution + the
  per-endpoint rate-limit dependencies), `dependencies.py` (`AuthContext`/`current_principal`/
  `current_user`/`require_verified` — the Day 4 API-key hook is a docstring on `current_principal`
  now, binding before any API-key code exists), `router.py` (all 9 endpoints).
- **New core modules** (`backend/app/core/`): `email.py` (`EmailSender` protocol, `SMTPEmailSender`
  via aiosmtplib, `FakeEmailSender` test double, the three render functions), `csrf.py`
  (`CSRFMiddleware`), `dependencies.py` (`get_settings_dep`/`get_clock`/`get_redis`/
  `get_password_hasher`/`get_dummy_password_hash`/`get_email_sender`).
- **Modified core**: `config.py` (every new `Settings` field — cookie/argon2/session/token-TTL/
  rate-limit/trusted-proxy fields — plus the `COOKIE_SECURE` production-guard check), `errors.py`
  (`ApiError` + its handler + the 415 mapping), `redis.py` (`incr_with_ttl`/`get_count`/`get_ttl`/
  `delete_key`, all through one atomic Lua script for the increment path, plus the breaker flag),
  `db.py` (`get_db_session` — rolls back on exception, never auto-commits; every writing route
  commits explicitly itself), `main.py` (the `clock`/`email_sender` DI seam, `app.state` wiring,
  `CSRFMiddleware`, `include_router`).
- **Infra**: `compose.yaml` (pinned `172.28.89.0/24` subnet on the `default` network, `caddy` at
  the static `172.28.89.10`), `compose.override.yaml` (`api`'s command now shell-form, adds
  `--proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"`), `.env` / `.env.example`
  (`COOKIE_SECURE`, `FORWARDED_ALLOW_IPS`, `TRUSTED_PROXY_IPS`, `ARGON2_*`).
- **Dependency**: `aiosmtplib==5.1.3` added to `backend/pyproject.toml` (resolved live via
  `uv add aiosmtplib` inside the container, then hand-pinned from the `>=` range `uv add` wrote,
  to `==`, matching this project's exact-pin convention; `uv lock` re-run to match).
- **Tests**: `tests/conftest.py` (split `client` into `app`+`client`, a `FakeEmailSender`/
  `SystemClock`-backed `app` fixture, a new autouse `_point_at_test_redis` fixture, and a
  hardened autouse `_flush_redis` fixture — see Known issues and the follow-up below),
  `tests/helpers.py` (+`make_user_with_password`, +`make_valid_session`), `tests/test_config_guard.py`
  (+1 test), and nine new files under `tests/auth/`: `conftest.py` (the shared `csrf_headers`
  fixture) plus `test_signup.py`, `test_password_policy.py`, `test_verify.py`, `test_login.py`,
  `test_logout.py`, `test_session_lifecycle.py`, `test_reset.py`, `test_csrf.py`, `test_rate_limit.py`.
- **CLAUDE.md**: two lines — the BackgroundTask email exception (Outbox bullet) and the Day 4
  `Authorization`-header rule (Security bullets).
- **Follow-up round**: `backend/app/core/config.py` (+`redis_url_test`), `.env`/`.env.example`
  (+`REDIS_URL_TEST=redis://redis:6379/15`); `docs/Cronos SRS.md` renamed to `docs/cronos-srs.md`
  (plain `mv`, content untouched — no other file referenced the old name except `README.md`,
  which already pointed at the lowercase form).

## Migrations
None. Every column Day 3 needed (`sessions`, `auth_tokens`) already existed from Day 2's
`0002_accounts_auth.py`.

## Tests: 93 → 140 (139 run by default, 1 explicit)
Day 2 ended at 92 run by default + 1 migration-marked (93 total). Day 3 adds 47 tests across the
9 new auth test files, landing at 139 run by default + 1 migration-marked = **140 total**. No
decrease. The suite was run three times back-to-back against the live container with identical
results (139 passed, 1 deselected each time) to rule out flakiness from the rate-limit/timing-
sensitive tests. Frontend Vitest unchanged at 3.

## Live verification (commands + real output, via Caddy on :8080)
All ten acceptance criteria run against the actual running stack:
1. **Signup → Mailpit → verify → replay**: `curl` signup → `201 {"message":"Check your email to
   verify your account."}`. Mailpit's search API showed the verification email with the link
   `http://localhost:8080/verify?token=...`. POSTing that token → `200 {"message":"Email
   verified."}`; replaying it → `400 {"error":{"code":"invalid_token",...}}`.
2. **Duplicate signup**: same email again → byte-identical `201` body. Mailpit now shows a second
   message, subject "Someone tried to register with your email" — not a second verification email.
3. **Login/cookies/CSRF/logout**: login's `Set-Cookie` showed `cronos_session=...; HttpOnly;
   Max-Age=2592000; Path=/; SameSite=lax` and `cronos_csrf=...; Path=/; SameSite=lax` (no
   `HttpOnly` on the CSRF cookie). `/me` → `200` with the full `UserPublic` body. A POST to
   `/verify/resend` without `X-CSRF-Token` → `403 csrf_failed`; with it → `200`. Logout → `204`,
   `Set-Cookie: cronos_session=""; Max-Age=0; ...`, CSRF cookie rotated, `/me` afterward → `401`,
   and `SELECT * FROM sessions` showed 0 rows.
4. **Wrong password vs. unknown email**: both produced the identical
   `401 {"error":{"code":"invalid_credentials","message":"Invalid email or password."}}`.
5. **Rate limit + Redis failover**: 15 rapid login attempts from one IP — the 11th through 15th all
   `429` with a shrinking `Retry-After` (42s → 40s). After the window cleared, `docker compose stop
   redis`, then login → `200` success, with exactly one `{"event":"redis_unavailable",...,"level":
   "warning"}` line in the api logs (not one per request). `docker compose start redis` restored it.
6. **Reset across two sessions**: two independent cookie jars logged in as the same user (different
   `cronos_session` values confirmed). `reset-request` → Mailpit → `/reset` with the token → `200`.
   Both jars' `/me` → `401` afterward. Old password → `401`; new password → `200`. Replaying the
   reset token → `400 invalid_token`.
7. **`SELECT id, length(id) FROM sessions`**: a 64-character hex string, confirmed equal to
   `sha256(<raw cookie value>)` computed independently — not the cookie value itself.
8. **Forged Origin**: a logout POST with `Origin: https://evil.example` → `403 origin_rejected`.
9. **Test counts**: 93 → 140 (139 default + 1 explicit), reported above; Vitest unchanged at 3.
10. **No CRLF** (`grep -rlI $'\r' backend/app backend/alembic backend/tests docs/progress` → no
    output). This file written before presenting the summary. No state-changing git commands run.

**Follow-up round**: `redis-cli -n 0 SET dev-canary-key still-here-from-dev` → ran `pytest -q` in
full (139 passed) → `redis-cli -n 0 GET dev-canary-key` → still `"still-here-from-dev"`, `DBSIZE`
on db 0 → `1` (only the canary); `DBSIZE` on db 15 → `0` (flushed clean by the last test). Then,
to prove the guard itself: ran `docker compose exec -e REDIS_URL_TEST=redis://redis:6379/0 api
pytest -q -k test_me_valid_session -x` — failed immediately with `RuntimeError: Refusing to flush
Redis: active REDIS_URL points at db '0', expected the dedicated test db '0' ... and never db 0`,
proving the fixture fails loudly rather than flushing on a bad config, before the real suite was
re-run clean (139 passed) with the correct `REDIS_URL_TEST`.

## Deviations from SRS / CLAUDE.md
The SRS is silent on every numeric specific here (rate-limit thresholds, token TTLs, session
lifetime, password policy, the dummy-hash requirement) — all of the following are this day's own
additions, not something already mandated:
- **Login rate-limit redesign** (mid-plan, before code): replaced a flat 5/15min-per-email limit
  with failure-only counting, split into `(email, IP)` (5/15min, resets on success) and
  per-email/all-IPs (30/hour, does not reset) — the original design was a lockout vector.
- **`incr_with_ttl` is one atomic Lua script**, not separate `INCR`/`EXPIRE`/`TTL` calls — a
  process dying between separate calls could leave a counter key with no expiry, i.e. a rate-limit
  key that never clears.
- **`get_db_session` does not auto-commit** on a clean return (only rolls back on exception); every
  writing route commits explicitly, before scheduling any `BackgroundTask`. The original plan
  relied on FastAPI's dependency-teardown ordering relative to `BackgroundTasks` — true today, but
  an implementation detail, not a contract worth building correctness on.
- **Signup's duplicate-email branch runs a real argon2 hash** (discarded), matching the fresh-signup
  branch's timing, for the same reason login's unknown-email path runs a dummy hash.
- **CSRF cookie rotates on login and logout** — a fresh value on every privilege change.
- **Caddy pinned to a static IP** (`172.28.89.10` in a pinned `172.28.89.0/24` subnet) so
  `FORWARDED_ALLOW_IPS`/`TRUSTED_PROXY_IPS` have a stable, correct address to trust — the subnet
  deliberately avoids `10.0.0.0/8` and `192.168.0.0/16` (including the common MikroTik default
  `192.168.88.0/24`) so it can't collide with a real LAN.
- **`ApiError`** extension to the error-handling system: Starlette resolves exception handlers by
  walking `type(exc).__mro__`, so registering a handler for the `ApiError` subclass doesn't disturb
  the existing generic `HTTPException`/404 handling.
- **Day 4 rule recorded now, in code and in CLAUDE.md**, before any API-key code exists: if
  `Authorization` is present, authenticate only by API key — an invalid key is a 401, never a
  silent fallback to the session cookie.
- **Logging discipline**: auth events log `user_id` and `sha256(email.lower())`, never the raw
  address; the same hash is what every email-keyed rate-limit key uses. No log line contains a
  password, a raw token, or a cookie value.

## Known issues / follow-ups
- **A real test-isolation gap was found and fixed during this day's work, then corrected again in
  a follow-up round because the first fix was itself unsafe**: Redis (rate-limit counters)
  persists across tests — unlike Postgres rows, which get fresh randomized data per test, a
  fixed-IP rate-limit key accumulates across *every* test in the session, which would cause
  cascading false `429`s in unrelated tests. The first fix added an autouse `_flush_redis` fixture
  that flushed whatever database `REDIS_URL` happened to point at — which was db 0, the **real dev
  database**, shared by the actual running `redis` container. Running the suite would have silently
  wiped live dev state. Fixed properly: a new `REDIS_URL_TEST` (db **15**, never 0) and a new
  autouse `_point_at_test_redis` fixture repoint `REDIS_URL` at it for the whole test session, the
  same pattern Day 1 already established for `DATABASE_URL`/`DATABASE_URL_TEST`. `_flush_redis`
  itself now **refuses to run at all** — raising `RuntimeError` instead of flushing — unless the
  active `REDIS_URL`'s database index is non-zero and matches `REDIS_URL_TEST` exactly, so a
  future regression in the repointing fails loudly instead of quietly flushing the wrong database.
  **Proved live**: set `dev-canary-key` in Redis db 0, ran the full suite (139 passed), confirmed
  the key was still present in db 0 afterward (`still-here-from-dev`, `DBSIZE` 1) while db 15 ended
  the run flushed clean; separately, pointing `REDIS_URL_TEST` at db 0 on purpose made
  `_flush_redis` raise immediately with a clear message, instead of flushing.
- `docs/Cronos SRS.md` has been renamed to `docs/cronos-srs.md` (plain `mv`, content byte-for-byte
  unchanged) — it had shown as modified in git status from outside this session (the IDE reported
  Oryn had it open; the diff was his own living-documentation update reflecting Day 2's decisions,
  not anything Claude touched). `README.md` already referenced the lowercase path; no other file
  referenced the old name.
- `GET /csrf` returns `200 {}` rather than `204` — chosen for curl-friendliness given the
  acceptance criteria are curl-driven; trivial to flip later if preferred.
- The common-passwords list (`backend/app/auth/common_passwords.txt`, ~100 entries) was assembled
  from well-known publicly published frequency lists, not pulled from a single canonical source
  file — fine for a launch-period deny-list, but worth swapping for a vetted list (e.g. a pinned
  SecLists file) if this ever needs to be defensible as "the" standard list.
- Session/token cleanup (expired rows) is still a maintenance job for a later day, per CLAUDE.md's
  existing TODO pointing at SRS §7 — nothing new added here.

## Commit block

```bash
git add -A
git commit -m "day 3: Auth — sessions, CSRF, signup/verify/login/logout/reset, fail-open rate limits" -m "- 9 endpoints under /api/v1/auth: GET /csrf, POST /signup|verify|verify/resend|login|logout|reset-request|reset, GET /me
- Cookie sessions: secrets.token_urlsafe(32) raw token, sha256 hex stored as sessions.id (the hash IS the PK, no separate column); 30-day absolute + 7-day idle expiry, both checked in SQL against now(); last_seen_at bumped at most once per 5 minutes via a self-gating UPDATE
- CSRF: double-submit cookie/header via a blanket CSRFMiddleware on every state-changing /api request (cookie-authenticated or pre-auth), constant-time compare, same-origin check, JSON content-type requirement, Authorization-header exemption as the Day 4 placeholder
- Login rate limits redesigned before any code was written: per-IP (10/min, every attempt) stays; the per-email limit became failure-only, split into (email, IP) 5/15min (resets on success) and per-email/all-IPs 30/hour (does not reset) — the original flat per-email design was a lockout vector
- FailOpenRedis gained incr_with_ttl (one atomic Lua script, so a counter key can never exist without a TTL), get_count/get_ttl/delete_key, and a breaker flag that logs one warning per outage episode, not per call
- Argon2 passwords with settings-driven cost params (prod = library defaults, zero config needed); hash/verify always off the event loop; a dummy hash (built from the same configured hasher) burns equivalent time on an unknown-email login, and signup's duplicate-email branch now does the same with a real discarded hash
- Transactional email (aiosmtplib, Mailpit in dev) via a FastAPI BackgroundTask scheduled only after each route's own explicit commit — not relying on dependency-teardown ordering; a capturing FakeEmailSender backs the whole test suite
- New ApiError exception class lets routes raise a specific code/field (invalid_credentials, email_not_verified, csrf_failed, origin_rejected, weak_password, invalid_token) without disturbing the existing generic HTTPException/404 handling
- Caddy pinned to a static IP (172.28.89.10 in 172.28.89.0/24, chosen to avoid colliding with real LANs) so FORWARDED_ALLOW_IPS/TRUSTED_PROXY_IPS have a stable, correct peer to trust for X-Forwarded-For
- Day 4's API-key rule recorded now in code (current_principal's docstring) and CLAUDE.md: Authorization present means auth by API key only, never a silent fallback to the session cookie
- Logging discipline: auth events log user_id + sha256(email), never the raw address, raw tokens, or cookie values — the same email hash backs every rate-limit key
- Test Redis isolation, fixed properly after an unsafe first attempt: tests now use a dedicated REDIS_URL_TEST (db 15, never 0), repointed each session the same way DATABASE_URL already was; the autouse flush fixture refuses to run at all (raises, does not flush) unless the active database index is confirmed non-zero and matches REDIS_URL_TEST exactly — proved live by a dev-db-0 canary key that survives a full suite run, and by the guard raising immediately when pointed at db 0 on purpose
- docs/Cronos SRS.md renamed to docs/cronos-srs.md (plain mv, content untouched) — README.md already referenced the lowercase path; no other file needed updating
- 93 -> 140 backend tests (139 run by default, 1 migration-marked run separately), stable across three consecutive full runs; Vitest unchanged at 3
- docs/progress/day-03.md added with full live-verification output (curl + Mailpit + a real Redis stop/start, plus the dev-db-0 canary proof) and every deviation"
```
