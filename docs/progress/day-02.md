# Day 2 summary

## What was built
Every table from the Cronos SRS data model (§5) now exists in Postgres, with integrity enforced
by the database, not just by Python: CHECK constraints on every status/kind/range field, partial
unique indexes that make one-open-incident-per-subject and the paused/is_active invariant real
database guarantees, composite `(account_id, x_id)` foreign keys that make a cross-account link
physically impossible to insert, a deferrable unique constraint so a status-page reorder can swap
two positions in one transaction, and a shared `set_updated_at()` trigger so `updated_at` is
maintained in SQL, never by the ORM. SQLAlchemy 2.0 typed models live in per-domain packages
(`accounts/`, `auth/`, `monitors/`, `heartbeats/`, `incidents/`, `notifications/`, `status_pages/`,
`core/`), all sharing one `Base`/naming convention; five hand-written Alembic migrations (0002–0006)
carry the actual DDL, with autogenerate used only as a first draft.

## Files changed (grouped by area)
- **Shared base**: `backend/app/db/{base,models}.py` — the naming-convention `Base` and the
  side-effect import that populates `Base.metadata` for Alembic.
- **Domain models** (new): `app/accounts/models.py` (Account, UsageEvent), `app/auth/models.py`
  (User, Session, ApiKey, AuthToken), `app/monitors/models.py` (Monitor, CheckResult,
  LatencyHourly), `app/heartbeats/models.py` (Heartbeat, HeartbeatPing), `app/incidents/models.py`
  (Incident), `app/notifications/models.py` (NotificationChannel, MonitorChannel,
  HeartbeatChannel, Notification), `app/status_pages/models.py` (StatusPage, StatusPageItem),
  `app/core/models.py` (ApiAlive, RunnerState, SystemState).
- **Alembic**: `alembic/env.py` (wired to the real `Base.metadata`), five new migrations
  `alembic/versions/0002_accounts_auth.py` … `0006_aggregates_metering_system.py`. `0001_baseline`
  untouched.
- **Core plumbing**: `app/core/db.py` — `create_engine()` now pins the asyncpg connection to UTC
  (`server_settings={"timezone": "UTC"}`), belt-and-suspenders with the DB-level `ALTER DATABASE`
  in 0002.
- **Tests**: `tests/conftest.py` gained `db_engine` (session-scoped, reuses the real
  `create_engine`) and `db_session` fixtures; new `tests/helpers.py` (plain row-building
  functions, no factory library); new `tests/{accounts,auth,monitors,heartbeats,incidents,
  notifications,status_pages,core}/test_constraints.py`; new `tests/test_migrations.py`
  (`alembic check` + the marked round-trip test).
- **Test config**: `pyproject.toml` gained the `migration` marker and `addopts = "-m 'not
  migration'"` so the destructive round-trip test is excluded from the default run.
- **Dev reload for every backend process** (follow-up): `compose.override.yaml` now bind-mounts
  `./backend:/app` into `migrate`, `runner` and `notifier` too (previously only `api` had it;
  `/opt/venv` stays image-baked, untouched by the mount). `runner`/`notifier` now run under the
  `watchfiles` CLI (`watchfiles --filter python --target-type command "python -m app.engine.runner"
  /app/app`, same shape for the notifier) instead of a bare `python -m ...`, so they restart on a
  code change the same way `uvicorn --reload` already did for `api`.

## Migrations
- **0002 — accounts/auth**: pins the database to UTC (`ALTER DATABASE ... SET timezone`),
  creates the `citext` extension and the shared `set_updated_at()` trigger function, then
  `accounts`, `users`, `sessions`, `api_keys`, `auth_tokens`.
- **0003 — monitoring**: `monitors` and `heartbeats` (each with its partial index — the runner
  claim index and the sweep index — and the `updated_at` trigger), `check_results` and
  `heartbeat_pings` (bigint identity PKs, composite + BRIN indexes).
- **0004 — incidents/alerting**: `incidents` (composite tenant FKs, the two partial-unique
  open-incident indexes), `notification_channels`, the `monitor_channels`/`heartbeat_channels`
  join tables (composite FKs that make a cross-account link physically impossible), `notifications`
  (the outbox, with a nullable composite FK to `incidents` relying on Postgres's `MATCH SIMPLE`).
- **0005 — status pages**: `status_pages`, `status_page_items` (three composite FKs, the
  `DEFERRABLE INITIALLY DEFERRED` unique position constraint, two partial-unique subject-dedup
  indexes).
- **0006 — aggregates/metering/system**: `latency_hourly`, `usage_events`, `api_alive`,
  `runner_state`, `system_state` — no triggers on any of these five.

## Tests: 12 → 93 (92 run by default, 1 explicit)
92 tests run in the default `pytest -q` pass; the migration round-trip test is marked
`@pytest.mark.migration` and excluded from the default run (it drops every table mid-session),
run explicitly via `pytest -q -m migration` (1 passed). Frontend Vitest unchanged at 3.

No decrease anywhere — this is a pure addition on top of Day 1's 12 backend / 3 frontend tests.
The jump from 84 to 93 in the follow-up round is the cause-list rewrite: `test_every_monitor_cause_
is_accepted` (7 cases, one per `http_status`/`timeout`/`connection`/`dns`/`tls`/`redirects`/
`blocked`) and `test_every_heartbeat_cause_is_accepted` (2 cases, `heartbeat_missed`/
`heartbeat_fail`) replace the single implicit assumption the old `monitor_failure_confirmed`/
`heartbeat_fail_ping` list carried.

## Live verification (commands + real output)
- **`docker compose down` → `docker compose build api` → `docker compose up -d`**: all 9
  services came up, `migrate` exited 0. (Rebuilding `api` was required — `migrate`/`runner`/
  `notifier` have no dev bind mount, only `api` does, so they needed the image rebuilt to see
  Day 2's code at all; see Known issues.)
- **`docker compose exec api alembic current`** → `0006 (head)`.
- **`\dt`** lists all 22 tables (`accounts`, `alembic_version`, `api_alive`, `api_keys`,
  `auth_tokens`, `check_results`, `heartbeat_channels`, `heartbeat_pings`, `heartbeats`,
  `incidents`, `latency_hourly`, `monitor_channels`, `monitors`, `notification_channels`,
  `notifications`, `runner_state`, `sessions`, `status_page_items`, `status_pages`,
  `system_state`, `usage_events`, `users`).
- **`\d monitors`** — confirms `ck_monitors_paused_matches_active`, `ck_monitors_timeout_range`,
  etc., the partial index `ix_monitors_next_check_at ... WHERE is_active`, `uq_monitors_account_id_id`,
  and the `trg_set_updated_at` trigger.
- **`\d incidents`** — confirms `ck_incidents_exactly_one_subject`, `ck_incidents_cause`,
  `ck_incidents_cause_matches_subject`, the two partial-unique open-incident indexes
  (`uq_incidents_open_monitor`/`_heartbeat`), both composite FKs to `monitors`/`heartbeats`, and
  the `SET NULL` FK to `users`.
- **`\d status_page_items`** — confirms `uq_status_page_items_page_position ... DEFERRABLE
  INITIALLY DEFERRED`, the two partial-unique subject-dedup indexes, and all three composite FKs.
- **Migration round trip**: `alembic downgrade base && alembic upgrade head` — clean, both on
  `cronos` and `cronos_test`, no errors.
- **`alembic check`** on both `cronos` and `cronos_test` → `No new upgrade operations detected.`
- **10,000-row EXPLAIN check** (throwaway `psql` script, wrapped in `BEGIN; ... ROLLBACK;` so
  nothing persisted — no separate delete step needed): the runner claim query's `due` CTE plans
  as `Index Scan using ix_monitors_next_check_at` (`Index Cond: next_check_at <= now()`, `Filter:
  is_active`); the heartbeat sweep query plans as `Bitmap Index Scan on ix_heartbeats_last_ping_at`.
  Both confirmed via `EXPLAIN (ANALYZE, BUFFERS)` against 10,000 live rows, then rolled back.
- **`pytest -q`** run twice back-to-back against the same `cronos_test` (no truncation between
  runs) → `83 passed, 1 deselected` both times, confirming the no-truncation/randomized-data
  isolation strategy actually holds under repetition.
- **`pytest -q -m migration`** → `1 passed`.
- **CRLF grep** (`grep -rlI $'\r' backend/app backend/alembic backend/tests docs/progress`) → no
  output.
- **`npx vitest run`** (frontend) → `3 passed`, unchanged from Day 1.

**Follow-up round** (after the above): rebuilt `api`, re-ran the full downgrade/upgrade round
trip on both `cronos` and `cronos_test` for the revised `incidents.cause` list, then re-ran
`alembic check` (both → `No new upgrade operations detected.`), `pytest -q` (`92 passed, 1
deselected`) and `pytest -q -m migration` (`1 passed`).

**Dev-reload proof** (`runner`/`notifier`, no rebuild): added a one-line `logger.info("runner_tick_
demo", ...)` inside `runner.py`'s `on_tick`. `docker compose logs runner` showed, within ~20s and
with zero `docker compose build`:
```
[18:30:56] 1 change detected
{"event": "runner_shutdown_complete", ...}
{"event": "database_ready", ...}
{"event": "runner_started", ...}
{"note": "hello from the hot-reload demo edit", "event": "runner_tick_demo", ...}
{"note": "hello from the hot-reload demo edit", "event": "runner_tick_demo", ...}
```
(repeating every 2s, matching `TICK_SECONDS`). Reverted the edit; `docker compose logs runner`
showed the same `1 change detected` → `runner_shutdown_complete` → `runner_started` sequence,
with no further `runner_tick_demo` lines afterward — `git diff --stat backend/app/engine/runner.py`
confirmed the file is byte-identical to its tracked state after the revert.

**`git status --porcelain --untracked-files=all`** — every line matches exactly this day's work:
5 new migrations (`0002`–`0006`, no strays), the 8 new domain-model packages (`accounts/`,
`auth/`, `monitors/`, `heartbeats/`, `incidents/`, `notifications/`, `status_pages/`, plus
`core/models.py`) and `db/{base,models}.py`, the matching 8 test packages plus `tests/helpers.py`
and `tests/test_migrations.py`, and 5 modified files (`alembic/env.py`, `app/core/db.py`,
`pyproject.toml`, `tests/conftest.py`, `compose.override.yaml`). Nothing unexpected — no leftover
model/migration files from the pre-existing volume state noted below, no stray scratch files.

## Deviations from SRS / CLAUDE.md
Three points were put to Oryn directly (per CLAUDE.md's "stop and ask" rule on SRS/CLAUDE.md
conflicts) and resolved before implementation:
1. **`accounts.updated_at`** — SRS §5 lists `account` as just `(id, plan, created_at)`; CLAUDE.md's
   "mutable config tables get `updated_at`" explicitly names `accounts`. Resolved: added it,
   following CLAUDE.md.
2. **`system_state.value`** — kept as `timestamptz`, not widened to `jsonb`, even though the table
   is described as "generic KV." Matches the only known key (`ingest_recovered_at`); a future
   non-timestamp key would need a schema change.
3. **`ck_incidents_cause_matches_subject`** — an extra CHECK beyond the literal spec, tying each
   `cause` value to its matching subject column. Resolved: included.

Also: **`auth_tokens`** is not in SRS §5 at all — added per CLAUDE.md's explicit Day 2 instruction,
needed for Day 3's email verification / password reset.

**`incidents.cause` fixed list** (SRS never enumerates it) — revised per Oryn's follow-up request,
before any data existed, by editing migration 0004 and the model directly rather than adding a
new migration:
- Monitor causes name the specific probe failure mode: `http_status`, `timeout`, `connection`,
  `dns`, `tls`, `redirects`, `blocked`.
- Heartbeat causes stay the original two: `heartbeat_missed`, `heartbeat_fail` (renamed from
  `heartbeat_fail_ping` to read as a cause rather than echo the outbox's `fail_ping` *event* name
  — the two are related but distinct concepts, and the rename makes that distinction clearer).

`ck_incidents_cause_matches_subject` still ties each cause to its correct subject column (monitor
causes require `monitor_id`, heartbeat causes require `heartbeat_id`), now checking membership in
`MONITOR_CAUSES`/`HEARTBEAT_CAUSES` (exported from `app/incidents/models.py`) rather than a single
literal per subject. `tests/incidents/test_constraints.py` gained
`test_every_monitor_cause_is_accepted`/`test_every_heartbeat_cause_is_accepted` (parametrized over
those same tuples) and `test_cause_must_match_subject_type` was updated to use `http_status`
instead of the old `monitor_failure_confirmed`. Re-verified after the change: `alembic downgrade
base && upgrade head` clean on both `cronos` and `cronos_test`, `alembic check` →
`No new upgrade operations detected.` on both, `pytest -q` → `92 passed, 1 deselected`.

## Known issues / follow-ups
- **A real naming bug was found and fixed during this day's work, worth remembering**: Alembic's
  `op.create_table` inherits `target_metadata.naming_convention` from `env.py` (since `env.py` sets
  `target_metadata = Base.metadata`). SQLAlchemy's `"ck"` naming-convention token *always*
  re-wraps a `CheckConstraint`'s name around the convention template — unlike `"uq"`/`"fk"`/`"pk"`,
  which only auto-name when no name is given. The first draft of every migration passed the
  *fully-qualified* name (e.g. `name="ck_monitors_confirm_threshold_range"`) to match the
  live-DB-friendly style used for FK/UQ names, which produced doubled names like
  `ck_monitors_ck_monitors_confirm_threshold_range` once applied. Fixed by giving every
  `CheckConstraint` in the migrations the *short local* name (e.g. `name="confirm_threshold_range"`),
  matching exactly what the ORM models already use — verified against a live `\d` after the fix.
  `alembic check` never caught this, because (confirmed separately) its comparator doesn't diff
  CHECK constraint names or bodies at all — only the hand-written constraint-violation tests
  actually exercise CHECK behavior, and those passed throughout since Postgres enforced the
  (oddly-named) constraints correctly regardless of their name.
- **Dev bind-mount gotcha — resolved this day**: only `api` had `./backend:/app` in
  `compose.override.yaml` originally; `migrate`, `runner`, `notifier` ran off the baked
  `cronos-backend:dev` image and needed an explicit `docker compose build api` before a `down`/`up`
  cycle would exercise new backend code at all. Fixed by bind-mounting `./backend:/app` into all
  three as well, and running `runner`/`notifier` under the `watchfiles` CLI so they restart on a
  change like `uvicorn --reload` already did for `api` — proven live (see above). `migrate` stays
  a one-shot command (no watchfiles needed there, just the mount) and still runs once per
  `docker compose up`, so a genuine schema change still needs a fresh `up` to apply, same as before.
- **`alembic check`'s real coverage** is narrower than its name suggests: it reliably diffs
  tables/columns/types/nullability/server-defaults/index-and-FK *presence*, but not CHECK
  constraint bodies or anything about triggers/functions. A green `alembic check` is evidence of
  schema-shape parity, not proof every CHECK/trigger is correct — that's what the hand-written
  constraint-violation tests are for.
- **`heartbeat_pings.user_agent`**: the 256-char limit is a hard-failing `CHECK`, not a
  DB-side auto-truncating trigger. Day 10's ping-ingest code must truncate before insert — an
  untruncated header reaching the DB as-is will raise `IntegrityError` rather than silently
  truncating. Flagged for the Day 10 implementer.
- The dev Postgres volume already contained a schema matching this exact table/column layout at
  the start of this session (predating any file I wrote today) — almost certainly leftover from
  an earlier attempt at this same day's work that was never committed. Resolved by running a full
  `alembic downgrade base` → `upgrade head` round trip against both `cronos` and `cronos_test`
  before any verification, so every table now provably comes from the migration files in this
  commit, not from unknown prior state.

## Commit block

```bash
git add -A
git commit -m "day 2: Full schema and migrations — every SRS table, DB-enforced integrity" -m "- 22 tables across accounts/auth, monitoring, incidents/alerting, status pages, and aggregates/metering/system, in 5 hand-written Alembic migrations (0002-0006) chained from 0001
- SQLAlchemy 2.0 typed models in per-domain packages, one shared Base with a pk_/fk_/uq_/ix_/ck_ naming convention; no cross-domain imports, no ORM relationship() — cascades are DB-level ON DELETE only
- Composite (account_id, x_id) foreign keys on incidents, monitor_channels, heartbeat_channels, notifications and status_page_items make cross-account links physically impossible to insert
- Partial unique indexes enforce one-open-incident-per-subject (makes ON CONFLICT DO NOTHING safe) and back the runner claim query (ix_monitors_next_check_at) and heartbeat sweep query (ix_heartbeats_last_ping_at)
- Deferrable UNIQUE (status_page_id, position) lets a status-page reorder swap two positions in one transaction; proven by a test pair that checks the swap commits clean while a genuine duplicate still fails at COMMIT, not flush
- Shared set_updated_at() trigger maintains updated_at in SQL, verified via a raw-SQL UPDATE test, not ORM onupdate
- UTC pinned both at the database level (ALTER DATABASE) and the asyncpg connection level (server_settings)
- auth_tokens added ahead of spec (not in SRS §5) for Day 3's verify-email/reset-password flows
- incidents.cause fixed list revised per review: monitor causes now name the specific probe failure (http_status / timeout / connection / dns / tls / redirects / blocked), heartbeat causes are heartbeat_missed / heartbeat_fail — edited directly in migration 0004 and the model since no data existed yet, with ck_incidents_cause_matches_subject kept and re-targeted at the new lists
- Dev reload now covers every backend process: migrate/runner/notifier bind-mount ./backend:/app (not /opt/venv) like api already did; runner/notifier run under watchfiles so they restart on a code change with no rebuild, proven live against the running stack and reverted clean
- Found and fixed a real naming bug: Alembic's op.create_table inherits target_metadata's naming convention, which always re-wraps CheckConstraint names even when already given — migrations now use short local names matching the ORM models, same as everywhere else
- 12 -> 93 backend tests (92 run by default, 1 destructive migration-round-trip test marked and run separately); one test per CHECK/UNIQUE/partial-unique/composite-FK/cascade rule, every cause value in the revised list, plus the required cross-account-link, deferred-constraint, trigger, and UTC proofs; Vitest unchanged at 3
- git status audited post-implementation: every changed/new file accounted for, nothing stray
- docs/progress/day-02.md added with full live-verification output, three Oryn-confirmed deviations, the incidents.cause decision and its review-round revision, and the dev-reload proof"
```
