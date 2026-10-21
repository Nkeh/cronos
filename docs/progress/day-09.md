## Day 9 summary

### What was built

- **Notifier process** (`app/notifier/`, new): rewrote `app/notifier/__main__.py`'s `on_tick`
  (was a no-op stub since Day 6) into a real drain loop, reusing `run_tick_loop` / the
  `_RunnerContext` shape / `_DB_UNAVAILABLE_ERRORS` backoff pattern from `app/engine/runner.py`
  exactly, via a new `_NotifierContext` (`app/notifier/context.py`). Claim (`claim.py`) is a
  `SKIP LOCKED` `UPDATE ... RETURNING` that reclaims both `pending` rows and **expired-lease**
  `sending` rows (`next_attempt_at <= now()` on either status) — a notifier that dies mid-delivery
  leaves a row that looks exactly like a fresh pending one once its lease expires, so the same row
  gets redelivered with the same id (used as `X-Cronos-Delivery`, so a receiver can dedupe) and an
  incremented `attempts`. Lease timestamps use `clock_timestamp()`, not `now()`, per the Day 8
  `claim.py` lesson (`now()` is pinned to transaction start, not evaluation time).
- **`bounded_transaction` parameterized, not copied** (`app/engine/db_bounds.py`): signature
  changed from `bounded_transaction(session, settings)` to
  `bounded_transaction(session, *, lock_timeout_ms, statement_timeout_ms)` so the notifier can
  pass its own `notifier_claim_*` settings through the same helper the runner uses. All three
  `runner.py` call sites plus every existing test that constructed one directly
  (`test_claim.py`, `test_cancellation_safety.py`) updated to pass the values explicitly —
  behavior is unchanged, only the call shape.
- **Delivery + outcome recording**: `deliver()` loads the channel fresh (outside the claim
  transaction — no DB connection held during the actual network call), checks the daily cap
  (suppressed if over), then dispatches to `deliver_email` or `deliver_webhook`. Outcome
  classification (`app/notifier/outcomes.py`) maps every case the plan specified: webhook `408`/
  `429`/`5xx` → retry (`429`'s `Retry-After` honoured, capped at 3600s), `3xx`/other `4xx` →
  failed (redirects are never followed — `follow_redirects=False, max_redirects=0`), SSRF-blocked
  → failed, timeouts/connection errors → retry; email SMTP `4xx` → retry, `5xx` → failed,
  connect/timeout → retry, unexpected exception → failed (never crashes the loop). Recording
  (`record.py`) always writes one `notification_attempts` row for an actual attempt (including a
  missing/unverified channel, so the delivery log explains *why* nothing went out) but **not** for
  a cap-suppressed claim (no attempt was made at all). Backoff schedule
  `60,300,900,3600` seconds, terminal failure at `notifier_max_attempts=5`.
- **Email delivery** (`app/notifier/email.py`): reuses `app/core/email.py`'s existing
  `SMTPEmailSender` directly (constructed by the notifier itself, not via `BackgroundTasks` — Day
  9 alert emails go through the outbox end to end, so a send failure feeds the retry
  classification instead of silently vanishing). New render functions for all 5 events
  (`opened`/`resolved`/`fail_ping`/`flapping` both phases/`cap_reached`), subjects using a small
  `app/notifications/cause_copy.py` mirror of the frontend's `causeCopy.ts` labels so subject
  lines read in plain English. All timestamps rendered UTC-explicit.
- **Webhook delivery + signing** (`app/notifier/webhook.py`, `signing.py`): reuses
  `HttpProbe.check`'s guarded-backend/SSRF-connect-time internals, but POSTs a freshly-built wire
  payload (SRS §10 shape — `id`/`event`/`occurred_at`/`incident{...}`/`monitor{...}`) rather than
  widening the stored `Notification.payload`, which stays `state.py`'s existing small internal
  shape. `X-Cronos-Signature: v1=HMAC-SHA256(secret, f"{timestamp}.{body}")`,
  `X-Cronos-Delivery` stable across retries of the same row. Webhook secrets encrypted at rest via
  a new `app/core/crypto.py` (Fernet, key SHA-256-derived from the arbitrary-length
  `ENCRYPTION_KEY` setting — a known limitation: rotating `ENCRYPTION_KEY` later breaks decrypting
  already-stored secrets; no rotation mechanism was requested this day).
- **Flapping** (SRS FR-6.3): entry is inline in `app/engine/state.py`'s existing incident-open
  branch, same transaction — the 3rd incident-open on a monitor within `flap_window_minutes=30`
  sets `monitors.flapping_since` and fires one `flapping` (`phase="started"`) notice *instead of*
  the normal `opened` notice; while flapping, every further open/resolve on that monitor is
  silent; an already-acknowledged open incident suppresses even the started notice (FR-5.4).
  Exit is a separate periodic sweep (`app/engine/maintenance.py`, new), run from the runner's
  `on_tick` on the same elapsed-time-gate pattern as the canary round, under
  `pg_try_advisory_xact_lock` — a conditional `UPDATE ... RETURNING` that clears `flapping_since`
  once a monitor has been `up` and incident-free for `flap_stable_minutes`, firing one `ended`
  notice; safe to run twice (second run finds nothing).
- **Daily caps** (SRS FR-6.5): checked at delivery time, not enqueue time (an outbox row still
  gets written; only *sending* is capped), counting `sent` rows today per account+channel-kind
  against `PlanLimits.alert_emails_per_day`/`webhooks_per_day`. Exactly one `cap_reached` notice
  is enqueued per account per kind per day via a `NOT EXISTS` guard — documented as an explicitly
  **soft** cap (two concurrent notifier tasks can both pass the guard before either commits).
- **Channels API** (`app/notifications/{router,schemas}.py`, new): full CRUD, save-time SSRF
  validation for webhook URLs (same `ssrf_policy` functions monitors use), `PATCH` on
  address/url resets `verified_at`, email verification (skips the email round-trip entirely when
  the address is the account's own already-verified email; otherwise a token link, reusing
  `auth/security.py`'s token helpers), webhook verification (one real signed test POST, 2xx →
  verified), secret reveal/rotate (`require_verified_session_user` — an API key gets 403
  `session_required`, same gate as API-key management), paginated delivery log, and monitor↔
  channel routing (`GET`/`PUT /api/v1/monitors/{id}/channels`, replace-the-full-set, 404s the
  whole request on any foreign channel id rather than partially applying).
- **Two confirmed hooks**: verifying the account email now inserts a verified, `is_default=true`
  `email` channel for that address in the same transaction as `email_verified_at`
  (`app/auth/router.py`); creating a monitor now auto-routes it to every `is_default` channel in
  the same transaction as the insert (`app/monitors/router.py`). Both fire going forward only —
  no backfill for pre-Day-9 accounts/monitors.
- **Chaos webhook receiver — Day 7 TODO closed** (`chaos/app/main.py`): `/webhook` now
  independently re-implements HMAC-SHA256 verification (not importing the backend's signing
  module — chaos is a separate deployable), checks a 300s freshness window, and logs
  `delivery_id`/`event`/`verified` per request. `ControlEntry` gained `webhook_secret` and
  `response_sequence` (a scripted status-code sequence, e.g. `[500, 500, 200]`, for retry tests)
  — both settable through the existing `/_control` mechanism, no new endpoint.
- **Frontend Channels UI**: `features/channels/` (list page, add-channel dialog, delivery-log
  drawer, HMAC-verification code snippet), a new `components/ui/Drawer.tsx` primitive (Radix
  `Dialog` + `motion/react`, slide-in from the edge — nothing like it existed before), a
  `/channels/verify` page (reads `?token=` but never auto-submits — same mail-scanner discipline
  as `/verify`), an "Alert channels" checkbox list on the monitor form (pre-selects defaults for a
  new monitor, lets either create or edit override the routing), and an Account-menu nav entry.

### Files changed (grouped by area)

**Migration / models**
- `backend/alembic/versions/0011_notifier_channels.py` (new)
- `backend/app/notifications/models.py` (`NotificationChannel.name`/`is_default`/
  `verify_token_hash`/`verify_expires_at`; new `NotificationAttempt`)
- `backend/app/plans/config.py` (`PlanLimits.max_channels`), `backend/app/plans/dependencies.py`
  (`"channels": NotificationChannel` in `_RESOURCE_MODELS`)

**Engine / notifier**
- `backend/app/engine/db_bounds.py` (`bounded_transaction` parameterized)
- `backend/app/engine/runner.py` (passes explicit timeout kwargs; schedules the flapping sweep)
- `backend/app/engine/state.py` (flapping entry hooks, inline in the incident-open branch)
- `backend/app/engine/maintenance.py` (new — flapping exit sweep, advisory-lock guarded)
- `backend/app/notifier/` (new: `context.py`, `claim.py`, `outcomes.py`, `record.py`, `caps.py`,
  `signing.py`, `email.py`, `webhook.py`, `delivery.py`); `__main__.py` (real `on_tick`)
- `backend/app/core/crypto.py` (new — Fernet secret encryption)
- `backend/app/core/email.py` (new render functions for all 5 notification events)
- `backend/app/notifications/cause_copy.py` (new), `service.py` (flapping/cap_reached enqueue
  helpers)
- `backend/app/core/config.py` (notifier/flap/cap/channel-verify settings,
  `check_production_guard()` refuses a placeholder/missing `ENCRYPTION_KEY`)
- `backend/app/core/db.py` is untouched; `backend/pyproject.toml` (`cryptography` pinned)

**API**
- `backend/app/notifications/router.py`, `schemas.py` (new — full Channels API)
- `backend/app/monitors/router.py` (`GET`/`PUT /{id}/channels`, default-channel routing hook)
- `backend/app/auth/router.py` (verify-hook: auto-create default email channel)
- `backend/app/main.py` (mounts the channels router)

**Chaos**
- `chaos/app/main.py` (real HMAC verification + `response_sequence` scripting on `/webhook`)

**Frontend**
- `frontend/src/features/channels/` (new: `hooks.ts`, `ChannelsPage.tsx`, `AddChannelDialog.tsx`,
  `DeliveryLogDrawer.tsx`, `SignatureSnippet.tsx`, + 3 new Vitest files)
- `frontend/src/pages/channels-verify/ChannelVerifyPage.tsx` (new, + Vitest file)
- `frontend/src/components/ui/Drawer.tsx` (new primitive)
- `frontend/src/lib/api/channels.ts` (new typed client), `types.ts` (channel/delivery types),
  `error-copy.ts` (`channelErrorMessage`)
- `frontend/src/app/router.tsx` (`/settings/channels`, `/channels/verify`)
- `frontend/src/app/shell/Navbar/AccountMenu.tsx` ("Notification channels" nav entry)
- `frontend/src/features/monitors/MonitorFormPage.tsx` ("Alert channels" routing checkboxes)

**Tests (backend, new)**
- `backend/tests/notifier/` (new dir: `conftest.py`, `test_signing.py`, `test_claim.py`,
  `test_record.py`, `test_caps.py`, `test_webhook.py` (live, against chaos), `test_email.py`
  (mocked `aiosmtplib`))
- `backend/tests/core/test_crypto.py`, `backend/tests/engine/test_maintenance.py`,
  `backend/tests/notifications/test_router.py` (live webhook-verify cases against chaos),
  `backend/tests/monitors/test_channels.py`

**Tests (backend, extended)**
- `backend/tests/engine/test_state.py` (+3 flapping tests), `test_claim.py`/
  `test_cancellation_safety.py` (`bounded_transaction` call-site signature updates only, no new
  tests), `backend/tests/notifications/test_service.py` (+4), `backend/tests/auth/test_verify.py`
  (+1), `backend/tests/test_config_guard.py` (+3 `ENCRYPTION_KEY` guard tests),
  `backend/tests/plans/test_config.py` (`_plan()` helper fix for the new `max_channels` field),
  `backend/tests/helpers.py` (`make_notification_channel` fix — was missing the now-required
  `name` column)

**Tests (frontend/Playwright, new/extended)**
- `frontend/tests/e2e/channels.spec.ts` (new), `helpers/chaos.ts` (extended: `webhook_secret`/
  `response_sequence` control, `getWebhookLog()`)
- `frontend/tests/e2e/axe.spec.ts`, `screenshots.spec.ts` (extended: channels pages, both themes)

### Migrations

- **`0011_notifier_channels`**: `notification_channels` gains `name` (NOT NULL, backfilled from
  `kind` for pre-existing rows, length-checked 1–60), `is_default` (NOT NULL default false),
  `verify_token_hash`/`verify_expires_at` (nullable). New `notification_attempts` table (bigint
  PK — a deliberate exception to CLAUDE.md's stated bigint list, same rationale as
  `check_result`/`heartbeat_ping`: high-volume, append-only log; flagged below). Replaces the
  Day-8 pending-only partial index on `notifications.next_attempt_at` with one covering
  `status IN ('pending','sending')` (needed so the claim query can find expired leases), and adds
  a `(account_id, sent_at)` partial index for the daily-cap count.

### Tests: 339 -> ~419 pytest (not executed this session — see Deviations); Vitest 9 -> 13 files, 45 -> 57 tests (executed)

```
cd frontend && npx vitest run --pool=threads
Test Files  13 passed (13)
     Tests  57 passed (57)
Duration    142.35s
```

```
cd frontend && npx tsc --noEmit
(clean, 0 errors)
```

```
cd frontend && npx eslint src/features/channels src/pages/channels-verify src/components/ui/Drawer.tsx \
  src/lib/api/channels.ts src/lib/api/types.ts src/lib/api/error-copy.ts src/app/router.tsx \
  src/app/shell/Navbar/AccountMenu.tsx src/features/monitors/MonitorFormPage.tsx
(exit 0, no output)
```

```
cd backend && python -m compileall -q app tests ../chaos/app
(clean, 0 errors)
```

The **~419 pytest figure is a count of new test functions added (80), not an executed number** —
see Deviations. Backend test tally for this day: 69 entirely-new-file tests
(`test_signing`=4, `test_claim`=9, `test_record`=7, `test_caps`=4, `test_webhook`=9, `test_email`=6,
`test_crypto`=4, `test_maintenance`=4, `test_router` (notifications)=19, `test_channels`
(monitors)=3) + 11 added to existing files (`test_state`+3, `test_service`+4, `test_verify`+1,
`test_config_guard`+3) = 80 new tests on top of Day 8's confirmed 339.

### Live verification (commands + real output)

**Docker Desktop was unavailable for the entire session** (checked at session start, mid-session,
and again immediately before writing this doc):

```
$ docker info
Server:
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the
path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system
cannot find the file specified.
```

With Docker down, there is no running Postgres, no `chaos` container, no Mailpit, and no
Playwright browser runtime available. What **was** verified, using a local Windows Python 3.12
and Node v22.20.0 install instead of the Compose stack:

- **Backend syntax**: `python -m compileall -q app tests ../chaos/app` — clean, every new/
  modified file (notifier modules, channels API, chaos receiver, all new test files) parses.
- **Frontend types**: `npx tsc --noEmit` — clean, 0 errors across the full frontend including the
  new channels feature, `Drawer.tsx`, and the monitor-form routing changes.
- **Frontend lint**: `npx eslint` over every new/modified frontend file — clean, exit 0, zero
  warnings or errors.
- **Frontend unit tests**: `npx vitest run --pool=threads` (see note below on `--pool=threads`) —
  full suite, 13 files / 57 tests, all passing, actually executed (not just authored).

**What was NOT executed this session, honestly flagged rather than assumed passing**:

- The full backend pytest suite (all ~419 tests, including every notifier/channels/flapping/caps
  test written this day) — requires real Postgres.
- `tests/notifier/test_webhook.py` and the live portions of `tests/notifications/test_router.py`
  — require the `chaos` container specifically.
- `tests/notifier/test_email.py`'s exact `aiosmtplib` exception constructor signatures
  (`SMTPResponseException(code, message)`, `SMTPConnectError(message)`, etc.) are written from
  training-data confidence, not confirmed against the actually-installed `aiosmtplib==5.1.3` —
  no environment with that dependency installed was available to import-check it.
- The entire Playwright suite, including the new `channels.spec.ts` and the `axe.spec.ts`/
  `screenshots.spec.ts` extensions — needs a running dev/prod build, Chromium, and the Compose
  network.
- Live acceptance steps 1–7 from the plan (real outage → email+webhook delivery latency, scripted
  `[500,500,200]` retry sequence, 404 permanent failure, lease-expiry redelivery after a killed
  notifier, flap start/stop notices, cap suppression + one `cap_reached` email, a mid-delivery DB
  restart) — all require the running Compose stack and were not attempted.
- `alembic upgrade head` / `alembic check` for migration `0011` — requires Postgres.

A sandbox-specific note for future sessions: Vitest's default `--pool=forks` hangs indefinitely in
this Windows/git-bash environment (`[vitest-pool-runner]: Timeout waiting for worker to respond`,
every file). `--pool=threads` works reliably and is now the way to run this suite here.

### Deviations from SRS / CLAUDE.md

- **Could not "verify against the running Compose stack," CLAUDE.md's own non-negotiable
  (Workflow rule 3).** Docker Desktop was down for the entire session despite being checked
  multiple times, including immediately before writing this doc. Everything that depends on
  Postgres/chaos/Mailpit/a browser runtime (the full pytest suite, Playwright, and all 8 live-
  acceptance steps from the plan) is authored and believed correct from careful reading of the
  existing Day 6–8 patterns it reuses, but is **unexecuted**. This is the day's primary deviation
  and should be the first thing re-run once Docker is available — `docker compose up -d --build`,
  `alembic upgrade head`, `pytest -q`, `npx playwright test` (+`@screenshots`), then the 8 live
  steps from the approved plan, in that order.
- **`notification_attempts.id` is a bigint PK**, a third exception to CLAUDE.md's stated
  `check_result`/`heartbeat_ping` bigint list, for the same reason: a high-volume, append-only log
  table where a UUID PK would add nothing and cost more per row.
- **`PlanLimits.max_channels` (10 for `launch`) is a new SRS §12 addition**, same precedent as
  Day 4's `max_api_keys` — not itself in the original SRS table, added for the same abuse-
  protection reasoning the rest of the limit seam exists for.
- **A second and third sanctioned exception to the outbox-only notification rule**, alongside
  Day 3's auth emails: (1) the channel email-verification link is sent via `BackgroundTasks`, not
  the outbox — it's account-setup plumbing, not an alert, and is trivially resendable; (2) webhook
  *verification* sends one real signed POST synchronously, inline in the request handler, so the
  caller gets an immediate verified/not-verified answer — this is the one place a notification-
  shaped send legitimately needs a synchronous result.
- **The stored `Notification.payload` and the actual webhook wire body are different shapes.**
  `state.py` keeps writing its existing small internal payload; the full SRS §10 wire payload
  (with nested `incident`/`monitor` objects) is rebuilt fresh at send time from a lookup, in
  `webhook.py`. Documented here and in the webhook module so a future reader isn't confused
  debugging a delivery by reading the stored row directly.
- **Daily send caps are intentionally soft** (FR-6.5): capped at the moment of send, not of
  enqueue, so an over-cap account still has every incident recorded; the one-per-day
  `cap_reached` notice uses a `NOT EXISTS` check that can itself race under concurrent notifier
  tasks (`notifier_concurrency=10`) and very rarely double-fire. Matches the brief's own framing
  of this as an acceptable, documented tradeoff rather than a bug to eliminate.

### Known issues / follow-ups

- Everything in this session is Docker-blocked for execution (see Live verification). The very
  next session must re-run the full verification chain before any further Day 10 work is
  layered on top of unexecuted Day 9 code.
- `aiosmtplib` exception signatures in `test_email.py` are unverified against the real package —
  flagged specifically so a failing import on first real pytest run isn't mistaken for a logic bug.
- No backfill was done (or asked for) for pre-Day-9 accounts without a default channel or
  pre-Day-9 monitors without routing — both hooks are forward-only, as confirmed with Oryn.

### Commit block

```bash
git add -A
git commit -m "day 9: notifier delivery, signed webhooks, channels API + UI, flapping, caps" -m "$(cat <<'EOF'
- Notifier (app/notifier/): claim with SKIP LOCKED reclaiming expired sending-leases
  (clock_timestamp(), same at-least-once id reused as X-Cronos-Delivery across retries), fixed
  backoff (60/300/900/3600s, max 5 attempts), no DB connection held during delivery.
- bounded_transaction (app/engine/db_bounds.py) parameterized instead of copied so the notifier
  reuses the runner's helper with its own timeout settings; all call sites updated.
- Email delivery reuses the existing SMTPEmailSender synchronously (not BackgroundTasks -- alert
  emails go through the outbox end to end so failures feed the retry classification).
- Webhook delivery reuses HttpProbe's guarded/SSRF-at-connect-time backend, no redirects
  followed, signed v1=HMAC-SHA256(secret, f"{timestamp}.{body}"); secrets encrypted at rest
  (app/core/crypto.py, Fernet). Wire payload rebuilt fresh at send time, separate from the small
  stored Notification.payload shape.
- Flapping (FR-6.3): 3rd incident-open in a 30-min window suppresses further per-incident alerts
  and fires one flapping-started notice instead; a periodic advisory-lock-guarded sweep
  (app/engine/maintenance.py) clears it after a stable window with one flapping-ended notice.
  Acked incidents suppress the started notice (FR-5.4).
- Daily send caps (FR-6.5), checked at send time, soft by design; exactly one cap_reached notice
  enqueued per account per channel kind per day.
- Channels API: full CRUD, save-time SSRF validation for webhooks, email/webhook verification,
  secret reveal/rotate (session-only), paginated delivery log, monitor<->channel routing.
- Two confirmed hooks: account-email verification auto-creates a default verified email channel;
  monitor creation auto-routes to every default channel. Both forward-only, no backfill.
- Chaos webhook receiver: real independent HMAC verification + scripted response_sequence,
  closing the Day 7 TODO.
- Frontend: channels feature (list/add/verify/test/reveal/rotate/delete/delivery-log), new
  Drawer primitive, /channels/verify page, monitor-form alert-channel routing, nav entry.
- Migration 0011: notification_channels.name/is_default/verify_token_hash/verify_expires_at,
  notification_attempts table, revised next_attempt_at index to cover expired sending-leases.
- Tests: 339 -> ~419 pytest (written, NOT executed -- Docker Desktop was unavailable all
  session), Vitest 9 -> 13 files / 45 -> 57 tests (executed, passing), tsc + eslint clean.
- Deviation: could not verify against the running Compose stack (CLAUDE.md workflow rule 3) --
  Docker Desktop was down throughout. Full pytest/Playwright/live-acceptance run against Postgres
  + chaos + Mailpit is the required first step of the next session.
EOF
)"
```
