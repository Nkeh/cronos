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

Verified this session against the real running stack:
```
$ docker compose exec api alembic current
0011 (head)
$ docker compose exec api alembic check
No new upgrade operations detected.
$ docker compose exec api alembic downgrade -1 && docker compose exec api alembic upgrade head
OK -- round trip clean, alembic check still clean afterward.
```

### Tests: 339 -> 423 passed, 1 deselected (pytest, executed); Vitest 9 -> 13 files / 45 -> 57 tests (executed)

```
$ docker compose exec api pytest -q
423 passed, 1 deselected in 251.24s (0:04:11)
```

```
$ docker compose exec frontend npx vitest run --pool=threads
Test Files  13 passed (13)
     Tests  57 passed (57)
```

Playwright (prod build, against the real Compose network) ran to **genuine completion under this
session's host conditions**, not a clean pass — see Live verification below for the honest
breakdown and why every failure is environmental, not a Day 9 regression.

### Live verification (commands + real output)

This session picked up Day 9 code that was written entirely while Docker Desktop was down and
had never been executed. Per this session's own governing instruction, step 0 was `docker info`
(engine was up this time) and the entire chain below was then run for real, fixing every failure
found along the way.

**a. Bring-up + migrations**
```
$ uv lock   # backend/pyproject.toml had cryptography==46.0.1 added last session without
            # regenerating uv.lock -- `uv sync --locked` refused to start until this ran.
$ docker compose up -d --build
$ docker compose exec api alembic upgrade head        # -> 0011 (head)
$ docker compose exec api alembic check                # -> No new upgrade operations detected.
$ docker compose exec api alembic downgrade -1 && docker compose exec api alembic upgrade head
                                                         # -> round trip clean
```

**b. Backend pytest** — fixed 20 real failures (19 test-authoring bugs, 1 real app bug), detailed
in "Deviations"/"Known issues" below:
```
$ docker compose exec api pytest -q
423 passed, 1 deselected in 251.24s (0:04:11)
```

**c. Vitest inside the container** (not host Node — a stray host-side `frontend/node_modules`
from an earlier host run exists on disk but is gitignored and confirmed untracked by `git
status`):
```
$ docker compose exec frontend npx vitest run --pool=threads
Test Files  13 passed (13)
     Tests  57 passed (57)
```
Two Radix Dialog/Drawer cold-start timeouts were seen on earlier runs (whichever test mounts the
first portal tree in a worker pays a one-time jsdom cost that can land past the 5000ms default
under this container's CPU budget); fixed by raising `testTimeout` globally in
`vitest.config.ts` to 15000ms rather than per-test, confirmed clean on three consecutive re-runs.

**d. Playwright** — default suite and `@screenshots`, prod build, against the real stack:
```
$ npx playwright test
11 passed, 5 failed, 34 did not run (globalTimeout 900s reached)

$ npx playwright test --grep '@screenshots'
0 passed, 1 failed, 1 did not run (its own 720000ms per-test override still exceeded)
```
Every one of the 6 failures is the identical signature: `Tearing down "context" exceeded the
test timeout of 30000ms` — browser-context **teardown**, after the test body itself already
finished, blowing the 30s ceiling under sustained host CPU contention (confirmed via `docker top`
showing real, accumulating chromium/renderer CPU time, not a hung/zero-activity process; and via
an isolated re-run of one such test passing cleanly in 96s with no other load on the host). This
is the same environmental characteristic CLAUDE.md already documents from Day 5b. Per Oryn's
explicit standing instruction, `playwright.config.ts`'s `timeout: 30000` was **not** raised to
paper over this — the honest result is reported as-is. No new contact sheets from `@screenshots`
exist to list: the one screenshot-matrix test did not complete.

**e. The 7 live-acceptance steps**, scripted against the real running stack (account/channel
setup via the real Channels/Monitors API, chaos via `/_control`, verification via direct
Postgres reads and Mailpit's API) — all 7 passed:

1. **Real outage → email + verified webhook, then recovery, with latency.** Dev's
   `FLAP_THRESHOLD=1` (`.env`) means a monitor's very first incident already crosses the flap
   threshold, so the actual event fired is `flapping` (phase `started`), not a plain `opened` —
   functionally the same DOWN notice through the same pipeline this step verifies (see Known
   issues). Real numbers:
   ```
   incident opened: 2.3s after outage
   DOWN notification (webhook): created_at 14:27:49.273  sent_at 14:27:49.958  latency 0.68s
   DOWN notification (email):   created_at 14:27:49.273  sent_at 14:27:49.964  latency 0.69s
   Mailpit subject: "[Cronos] FLAPPING: Live 1 - outage+recovery"
   chaos webhook log: verified=true
   incident resolved: 2.2s after recovery
   ```
   Both latencies are far under NFR-3's <10s median. The resolved notice is correctly silent while
   flapping (FR-6.3) — exercised explicitly in step 5.
2. **Scripted `[500, 500, 200]` webhook retry.**
   ```
   notification_attempts: [('retry', 500), ('retry', 500), ('sent', 200)]
   chaos log, 3 deliveries, same id: 07ff9ae1-dda0-4479-be69-009b686c7fd6 (x3)
   final status: sent
   ```
3. **404 → permanent failure, no retry.**
   ```
   final status=failed attempts=1 notification_attempts=[('failed', 404)]
   ```
4. **Lease recovery after killing the notifier mid-delivery.** Polled until a claimed row hit
   `status='sending'`, `docker compose kill -s SIGKILL notifier` at that instant, waited past the
   dev 10s lease, restarted the notifier:
   ```
   attempts: 1 -> 2 (reclaimed)
   notification_attempts: exactly 1 row (outcome=sent) -- the killed first attempt never got to
     record_outcome, proving it genuinely never wrote anything
   chaos webhook log: same delivery id (62a9fc88-...) arrives exactly once, verified=true
   ```
5. **Flapping started/ended notices** (dev `FLAP_WINDOW_MINUTES=1`, `FLAP_STABLE_MINUTES=1`,
   `FLAP_THRESHOLD=1`):
   ```
   flapping_since set -> flapping-started notice sent -> (stable window) -> flapping-ended
   notice sent -> flapping_since cleared
   ```
6. **Cap suppression + exactly one `cap_reached`.** `PlanLimits.webhooks_per_day=500` has no dev
   override (by design — CLAUDE.md: no hard-coded limits outside `PLANS`), so "already at cap"
   was simulated with 500 synthetic `sent` rows for the test account, then a real send attempted:
   ```
   over-cap notification status: suppressed
   cap_reached rows today for this account+channel: 1
   ```
7. **`docker compose restart db` mid-delivery.** Polled until a row hit `sending`, restarted
   `db`, waited for it to report healthy again:
   ```
   db healthy again in ~12s; in-flight delivery (no DB connection held during the actual send)
   completed and wrote its outcome on the first attempt once Postgres was back
   attempts=1, status=sent
   SELECT * FROM notifications WHERE status='sending' AND next_attempt_at < now(); -- 0 rows
   ```
   Nothing anywhere in the account was left stuck in `sending` past its lease.

### Deviations from SRS / CLAUDE.md

- **A real Day 9 bug, found and fixed this session**: `app/engine/runner.py` and
  `app/notifier/__main__.py` never imported `app.accounts.models` (or most other domain models)
  — every pre-Day-9 write in these processes went through raw parameterized SQL, which never
  needed a model class to exist. Day 9's `enqueue_notifications`/`enqueue_flapping_notification`
  (`app/notifications/service.py`) is the **first** ORM `session.add()` in either process's
  history, building a `Notification` row whose `account_id` column is a string
  `ForeignKey("accounts.id")`. SQLAlchemy resolves that lazily against `Base.metadata` at flush
  time — and since `accounts` (and everything else these processes never otherwise imported) was
  missing from it, **every single incident notification ever enqueued from the runner or
  notifier raised `sqlalchemy.exc.NoReferencedTableError`**, silently caught by the broad
  `except Exception` handler and logged as `check_task_unexpected_error`/
  `notification_task_unexpected_error` — rolling back the *entire* transaction, including the
  check-result write it shared, so a monitor could fail forever without ever producing a
  `check_results` row. This is not dev-config-specific: in production (`flap_threshold=3`, not 1)
  the very first "opened" notification on any monitor's third incident would hit the identical
  crash. Fixed with the same one-line fix `alembic/env.py` already uses for the same reason:
  `from app.db import models as _all_models  # noqa: F401`, added to both entrypoints. Confirmed
  via direct `Base.metadata.tables` introspection before/after, and via the full live-acceptance
  run above (every step depends on this working).
- **Could not get a clean Playwright run** — see Live verification (d). Reported honestly per
  CLAUDE.md; not treated as a Day 9 regression per the Day 5b precedent, and the 30s test
  ceiling was deliberately left untouched.
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

- **Dev's `FLAP_THRESHOLD=1` (`.env`) makes a plain, non-flapping "opened"/"resolved" notice
  unreachable in this dev stack** — every monitor's very first incident already crosses the
  threshold, so the normal per-incident notice is always replaced by a flapping one, and the
  normal "resolved" notice is always suppressed. This was deliberately set low so flapping itself
  is fast to test (step 5), but it means the plain-path code (`enqueue_notifications`'s `opened`/
  `resolved` branch, exercised directly in pytest, just never exercised live in dev as currently
  configured). Not a product bug — flag for whoever next tunes dev `.env` values.
- `dev_fixtures.create_user` (used by Playwright's global-setup and the `/_dev/users` endpoint)
  does not replicate `app/auth/router.py`'s real verify-hook: a dev-created `verified=true` user
  gets no auto-created default email channel, unlike a real signup→verify flow. No current test
  depends on this, but it's a latent gap if a future Playwright fixture assumes one exists.
- A stale `runner_state` row from an old, already-dead runner instance (`last_tick_at` from
  2026-10-15) was found sitting in the table during this session's investigation — nothing reads
  or acts on it, but there's no reaper for `runner_state` rows left behind by a runner that was
  killed hard enough to skip its own shutdown cleanup. Harmless today; worth a cheap TTL-based
  sweep eventually.
- `frontend/node_modules` exists on the host (from an earlier host-side Vitest run) — confirmed
  gitignored and untracked by `git status`; the container uses its own named volume and does not
  read this directory. No action needed, flagged per this session's instructions.

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
- Fixed a real bug found this session: the runner and notifier processes never imported
  app.accounts.models (everything pre-Day-9 used raw SQL), so the first ORM flush of a
  Notification row's account_id FK raised NoReferencedTableError and silently rolled back every
  incident-notification transaction. Fixed with the same models aggregator import alembic/env.py
  already uses.
- Fixed 19 test-authoring bugs surfaced by actually running pytest for the first time this day
  (CSRF content-type on bodyless POSTs, a nonexistent-route assumption, a test-helper auto-fill
  defeating its own test, a copy-paste assertion, a missing CSRF fixture, unrealistic None
  defaults in test_email.py) plus one real app bug (_RESOLVE_INCIDENT_SQL's now() vs
  clock_timestamp(), same class of issue as Day 8's claim.py).
- Tests: 339 -> 423 passed, 1 deselected (pytest, executed against real Postgres); Vitest 9 -> 13
  files / 45 -> 57 tests (executed). Migration 0011 verified: upgrade/check/downgrade/upgrade
  round trip clean.
- All 7 live-acceptance steps run against the real stack and passing: outage->email+webhook
  latency (~0.7s), [500,500,200] retry, 404 permanent failure, notifier-kill lease recovery,
  flapping started/ended, cap suppression + single cap_reached, db-restart mid-delivery with
  nothing left stuck in 'sending'.
- Deviation: Playwright did not complete cleanly (11 passed / 5 failed / 34 not-run on the
  default suite, 0/1/1 on @screenshots) -- every failure is "Tearing down context exceeded
  30000ms" under sustained host CPU contention (same class as the documented Day 5b precedent),
  not a Day 9 regression; the 30s ceiling was deliberately left unraised per standing instruction.
EOF
)"
```
