## Day 5b summary

### What was built

**Playwright hardening** (done first, before any feature work, per explicit instruction — see
the dedicated section below for the full diagnosis). `playwright.config.ts` now has a hard
`globalTimeout` (15 min), a 30s per-test timeout, a 10s `expect` timeout, and `workers: 1`
(empirically required — see "What was actually wrong"). Every helper that polls or navigates
(`global-setup.ts`, `helpers/dev-fixtures.ts`, `helpers/auth.ts`, `helpers/deadline.ts`) has an
explicit, named deadline. Every shell invocation of pytest/Vitest/Playwright in this session ran
under a `timeout`-wrapped command.

**Dev CLI + fixture backdoor** — `backend/app/dev_fixtures.py` (shared logic), `backend/app/
cli.py` (`python -m app.cli create-user|seed-demo`, refuses under `ENV=production` before
touching the DB), `backend/app/dev/router.py` (`POST /_dev/users`, `/_dev/users/delete`,
`/_dev/seed-monitors` — only mounted when `settings.env != "production"`, in `app/main.py`).
Playwright's fixtures (`helpers/dev-fixtures.ts`) call this HTTP backdoor instead of driving real
signup, and `global-setup.ts` deletes-then-recreates four fixture accounts (`emptyMonitors`,
`seeded`, `limit`, `unverifiedMonitors`) every run, since the dev database persists across runs
unlike the test database.

**Monitor UI** — `features/monitors/MonitorsListPage.tsx` (status pill incl. new `new` variant,
usage bar, pause/resume with optimistic rollback, check-now, delete via `ConfirmDialog`, a
designed empty state) and `MonitorFormPage.tsx` (one component for both create and edit,
pre-populates every field from the GET response in edit mode, an Advanced disclosure for
interval/timeout/confirm-threshold, plan-limit and unverified-email gating on the CTA). New API
client (`lib/api/monitors.ts`), hooks (`features/monitors/hooks.ts`, TanStack Query optimistic
`onMutate`/`onError` pattern for pause/resume), error-copy map, `ConfirmDialog`/`UsageBar`
primitives, `lib/relativeTime.ts`. Both routes are lazy-loaded in `app/router.tsx`. Overview (`/`)
now shows real per-status monitor counts via `useMonitors()`.

**Contrast fixes** — recomputed WCAG contrast by hand for every status token against all three
surfaces in both themes (not just two, and not an estimate, as Day 5a's table was). Two light-
theme colors were actually failing AA and are fixed; full table below.

**Dev rate limits** — `.env`/`.env.example` raise the four auth rate limits ~4x over their coded
production defaults, so repeated local Playwright runs don't trip them. (First pass raised them
~20x, which broke two pytest rate-limit tests — see Deviations.)

### Files changed (grouped by area)

- **Dev CLI / fixtures (new)**: `backend/app/dev_fixtures.py`, `backend/app/cli.py`,
  `backend/app/dev/__init__.py`, `backend/app/dev/router.py`, `backend/app/main.py` (mounts the
  dev router outside production)
- **Dev CLI / fixtures tests (new)**: `backend/tests/test_cli.py`, `backend/tests/dev/__init__.py`,
  `backend/tests/dev/test_dev_router.py`
- **Monitor UI (new)**: `frontend/src/features/monitors/` (`MonitorsListPage.tsx`,
  `MonitorFormPage.tsx`, `hooks.ts`), `frontend/src/lib/api/monitors.ts`,
  `frontend/src/lib/relativeTime.ts`, `frontend/src/components/ui/ConfirmDialog.tsx`,
  `frontend/src/components/ui/UsageBar.tsx`
- **Monitor UI (modified)**: `frontend/src/app/router.tsx` (lazy monitor routes),
  `frontend/src/lib/api/types.ts`, `frontend/src/lib/api/error-copy.ts`,
  `frontend/src/components/ui/Button.tsx` (exported `buttonVariants`),
  `frontend/src/components/ui/StatusPill.tsx` (`new` status), `frontend/src/pages/overview/
  OverviewPage.tsx` (real counts)
- **Tokens/contrast**: `frontend/src/styles/index.css`, `frontend/design/tokens.md`
- **Dev env**: `.env`, `.env.example` (rate limits)
- **Playwright hardening/infra**: `frontend/playwright.config.ts`, `frontend/tests/e2e/
  global-setup.ts`, `frontend/tests/e2e/helpers/auth.ts`, `frontend/tests/e2e/helpers/
  shared-user.ts`, `frontend/tests/e2e/helpers/deadline.ts` (new), `frontend/tests/e2e/helpers/
  dev-fixtures.ts` (new)
- **Playwright specs**: `frontend/tests/e2e/monitors.spec.ts` (new), `frontend/tests/e2e/
  auth.spec.ts`, `frontend/tests/e2e/axe.spec.ts`, `frontend/tests/e2e/navbar.spec.ts`,
  `frontend/tests/e2e/screenshots.spec.ts`
- **Process doc**: `CLAUDE.md` (one line added to Testing — see below)

### Migrations

None — Day 5b is UI, CLI and test-infra work against the Day 4 monitor schema/API; no model
changes.

### Where the earlier hang was, and how it was fixed

Two prior sessions lost over an hour (once 13 hours) to a Playwright invocation that produced no
output and never exited. Diagnosis this session, in the order run:

1. **`globalSetup` alone** (`--grep "zzz-no-such-test-zzz"`, nothing matches, so only setup runs):
   clean, 62.8s, every fixture create/login step logged with a running `+Ns` timestamp. No stall.
2. **A single spec** (`auth.spec.ts`) with the *old* `fullyParallel` default (no `workers` pin):
   3 of 4 tests blew the 30s per-test timeout — not a hang, a loud bounded failure, but revealing
   real contention: `docker stats` showed `api` (uvicorn `--reload` under
   `WATCHFILES_FORCE_POLLING`) at ~80% CPU and `frontend` (Vite, same polling) at ~43%, sustained,
   on a 4-CPU host running 9 containers. That polling is a deliberate, pre-existing trade-off
   (`.env.example`: "bind mount; polling is slower but reliable" on Windows) — not a Day 5b
   regression — but it is expensive enough on this host to starve the test browser's own CPU
   scheduling intermittently.
3. Pinning `workers: 1` cut the failures from 3/4 to 2/4 on the same spec, confirming parallelism
   made it worse but wasn't the sole cause — one failure was a plain `.fill()` on an
   already-loaded page hanging for the full 30s, i.e. Chromium itself stalling, not the network.
   A bounded navigation retry (`gotoRetrying`, two attempts at 20s each) was added and applied to
   every `page.goto` across the suite; this fixed most, but not all, of the remaining flakiness.
4. **The full default suite**, run twice: first at 15/37 → fixed two real bugs it exposed (an
   axe contrast test and a rollback test — see below) → re-run at 34/37, the 3 remaining failures
   all being the same host-CPU-contention Chromium stall in `auth.spec.ts`/`monitors.spec.ts`'s
   longest, most-navigation-heavy flows. Never silent, never past 30s per test.
5. **The `@screenshots` suite**, run three times: first failed immediately (a 15s nav timeout with
   no retry); fixed by applying `gotoRetrying` there too; second run captured all 144 screenshots
   correctly but reported "failed" because the internal `test.setTimeout` (10 min) elapsed during
   final-context teardown, a few seconds after the last capture; widened to 12 min; third run
   passed clean.

**Two real bugs found and fixed along the way** (not environment flakiness):
- `axe.spec.ts`'s `/monitors/:id/edit` check ran `AxeBuilder.analyze()` immediately after
  clicking into the edit page, racing the GET-then-populate-then-CSS-transition sequence in
  `MonitorFormPage`. Under this host's contention the window widened enough that axe sometimes
  measured a mid-transition blended color as a false "insufficient contrast" violation. Fixed by
  emulating `reducedMotion: 'reduce'` (which zeroes `transition-duration` globally per
  `index.css`'s existing rule) and waiting for the real value to land before scanning — no
  arbitrary sleep.
- `monitors.spec.ts`'s "pause rolls back on a failed request" test created its monitor through
  the full real UI create-form flow first, which was eating most of the 30s budget before the
  actual assertion under test even started. Rewritten to seed the one monitor it needs via the
  dev-fixture backdoor instead, leaving the full budget for the thing being tested.

**Timeout rules now in place**:
- `playwright.config.ts`: `globalTimeout: 15 * 60 * 1000`, `timeout: 30000`,
  `expect: { timeout: 10000 }`, `reporter: 'line'`, `workers: 1`.
- `global-setup.ts` and every dev-fixture/login helper: wrapped in `withDeadline(promise, ms,
  label)` (`helpers/deadline.ts`), which races the real work against a named timer and throws
  "Timed out after Nms waiting for: <label>" — never a silent stall.
- Every `docker compose exec`/`run` invocation in this session (pytest, Vitest, both Playwright
  suites) ran under a shell-level `timeout N ...` wrapper, chosen with headroom over Playwright's
  own `globalTimeout` so the shell timeout is a true last resort.

### Tests: 208 → 217 (pytest) · 26 → 26 (Vitest, unchanged) · 23 → 37 (Playwright)

**pytest**: 217 passed, 1 deselected (`tests/dev/`, `tests/test_cli.py` new: CLI/dev-router
create-user/seed-demo, production-guard refusal, idempotent delete-and-cascade). One real
regression surfaced and fixed mid-session: the first-pass dev rate limits (raised ~20x) made
`test_login_per_ip_limit` and `test_x_forwarded_for_ignored_from_untrusted_source` flake (401
instead of 429) — looping ~200 real argon2 logins is slow enough on this host that Redis's
fail-open circuit breaker occasionally tripped mid-loop, correctly-by-design but breaking the
test's assumption of always hitting the limit. Fixed by dialing the raise back to ~4x (see
Deviations) rather than disabling or weakening the test.

**Vitest**: unchanged at 26 (6 files) — Day 5b added no new frontend unit tests; all new coverage
is Playwright e2e against the real stack.

**Playwright**: 23 → 37 (new: the monitor CRUD flow, pause-rollback, blocked-URL, plan-limit and
unverified-account specs in `monitors.spec.ts`; axe and the screenshot matrix extended to five
new monitor-related pages; navbar's content-row test re-targeted at real monitor rows). Final
default-suite run: 34 passed, 3 failed — all three are the same pre-existing host-CPU-contention
Chromium stall described above, reproduced consistently in `auth.spec.ts`'s two longest flows and
`monitors.spec.ts`'s full CRUD flow, never a hang (always a clean, bounded 30s failure). The
`@screenshots` suite: 1/1 passed, 144/144 screenshots captured.

### Live verification (commands + real output)

```bash
docker compose up -d --build                                  # full stack healthy
docker compose exec api alembic upgrade head                   # no-op, no new migrations
docker compose exec api python -m app.cli create-user --email demo@example.com --password ... --verified
docker compose exec api python -m app.cli seed-demo --email demo@example.com
```

Backend — `timeout 300 docker compose exec api pytest -q`:
```
217 passed, 1 deselected in 210.93s (0:03:30)
```

Frontend unit — `timeout 180 docker compose exec frontend npx vitest run`:
```
Test Files  6 passed (6)
     Tests  26 passed (26)
  Duration  26.30s
```

Lint — `timeout 120 docker compose exec frontend npm run lint`: 0 errors.

Build — `timeout 180 npm run build` (chunk sizes, gzip):

| Chunk | Day 5a | Day 5b |
|---|---|---|
| Main (`index-*.js`) | 577 kB / 185 kB gzip | 593.90 kB / 190.74 kB gzip |
| `MonitorsListPage` | — | 7.31 kB / 2.76 kB gzip (lazy) |
| `MonitorFormPage` | — | 4.27 kB / 1.79 kB gzip (lazy) |

Both new monitor routes are properly code-split, as required; the main chunk grew modestly
(Overview now does real work against `useMonitors()`).

Playwright default suite — `timeout 1200 docker compose --profile tools run --rm pw-tests npx
playwright test --grep-invert "@screenshots"`:
```
34 passed, 3 failed (auth.spec.ts x2, monitors.spec.ts x1 — see above)
Wall clock: 13:11:06 -> 13:24:47  =  13m 41s
```

Playwright `@screenshots` suite — `timeout 900 docker compose --profile tools run --rm pw-tests
npx playwright test --grep "@screenshots"`:
```
1 passed
Wall clock: 14:32:27 -> 14:44:04  =  11m 37s
```

Contact sheets built — `timeout 120 docker compose --profile tools run --rm pw-tests node
tests/e2e/build-contact-sheets.mjs`, one PNG grid per page at
`frontend/tests/screenshots/contact-sheets/<page>.png`:
```
dev-design.png   forgot.png        login.png          monitor-edit.png
monitor-new.png  monitors-empty.png monitors-seeded.png overview.png
overview-seeded.png reset.png      signup.png          verify.png
```
(The first 7 are Day 5a's pages, regenerated; the 5 new Day 5b pages are `monitors-empty`,
`monitor-new`, `overview-seeded`, `monitors-seeded`, `monitor-edit`.)

**Diagnosis runs** (not part of the final numbers above, run in sequence while isolating the
hang — see "Where the earlier hang was"):
```
globalSetup alone:                              62.8s,  clean
auth.spec.ts, fullyParallel (2 workers):          ~3m,  1 passed / 3 failed
auth.spec.ts, workers: 1:                        2.9m,  2 passed / 2 failed
default suite, before axe/rollback fixes:       15.0m,  27 passed / 6 failed / 4 cut by globalTimeout
@screenshots, before gotoRetrying fix:            ~2m,  failed on the very first navigation
@screenshots, after fix, before timeout widen:   11.3m,  144/144 captured, reported failed at teardown
```

**Contrast table** (`frontend/design/tokens.md`, WCAG relative luminance vs all three surfaces
each theme uses):

Dark theme (`bg #080A08` / `surface #111611` / `surface-raised #1A221A`):

| Token | vs `bg` | vs `surface` | vs `surface-raised` |
|---|---|---|---|
| `text` `#F0F5F0` | 18.00:1 | 16.59:1 | 14.77:1 |
| `text-muted` `#8A9E8A` | 6.94:1 | 6.40:1 | 5.70:1 |
| `status-up-text` `#00C853` | 8.88:1 | 8.18:1 | 7.29:1 |
| `status-down-text` `#FF6E6E` | 7.29:1 | 6.72:1 | 5.99:1 |
| `status-degraded-text` `#FFC24B` | 12.36:1 | 11.39:1 | 10.15:1 |
| `status-paused-text` `#9CA3AF` | 7.82:1 | 7.22:1 | 6.42:1 |
| `status-new-text` `#8296BE` | 6.67:1 | 6.15:1 | 5.48:1 |

Light theme (`bg #F7F9F7` / `surface #FFFFFF` / `surface-raised #EFF3EF`):

| Token | vs `bg` | vs `surface` | vs `surface-raised` | Status |
|---|---|---|---|---|
| `text` `#0B140B` | 17.74:1 | 18.77:1 | 16.74:1 | unchanged |
| `text-muted` `#3F4F3F` | 8.26:1 | 8.74:1 | 7.80:1 | unchanged |
| `status-up-text` `#007A36` | 5.18:1 | 5.48:1 | 4.88:1 | **fixed** — was `#00A847`, ~2.8-3.1:1, failing AA |
| `status-down-text` `#C9372C` | 4.88:1 | 5.17:1 | 4.61:1 | unchanged, confirmed (tightest margin) |
| `status-degraded-text` `#8C6200` | 5.14:1 | 5.44:1 | 4.86:1 | **fixed** — was `#946800`, 4.42:1 vs `surface-raised`, just under AA |
| `status-paused-text` `#5B6472` | 5.66:1 | 5.98:1 | 5.34:1 | unchanged, confirmed |
| `status-new-text` `#44588A` | 6.60:1 | 6.98:1 | 6.23:1 | new token |

Every pair is now ≥4.5:1 (AA, normal text) in both themes.

Manual click-through against the live stack: created a monitor pointed at `http://chaos:8000/
health`, edited it and confirmed every field (name/url/method/expected_status) round-tripped from
the GET, paused and resumed (optimistic UI, instant), check-now (toast), deleted via the confirm
dialog, hit the 15-monitor limit on the `limit` fixture account and saw the disabled CTA + usage
bar at 15/15, toggled theme on `/monitors` and `/monitors/:id/edit` and confirmed the corrected
light-theme contrast renders legibly.

### Deviations from SRS / CLAUDE.md

- **Playwright `workers: 1`, kept from Day 5a rather than flipped to parallel** as the inherited
  plan intended. Measured directly this session: 2 workers against this sandbox's dev server
  (Windows bind-mount + forced file-watch polling, a pre-existing trade-off) was enough
  contention to blow the 30s per-test timeout on ordinary form actions that take ~1-2s running
  alone. Per CLAUDE.md's instruction that the 30s ceiling itself must not move, concurrency was
  the dial that had to move instead.
- **Dev rate limits raised ~4x, not an arbitrary large number.** First attempt raised them ~20x
  (to 100-200), which broke two pytest rate-limit tests by making their loop-to-the-limit logic
  slow enough to occasionally trip Redis's intentional fail-open circuit breaker. Dialed back to
  signup 20 / login 40 / reset-email 12 / reset-ip 40 — still comfortable headroom for repeated
  local Playwright runs, without the side effect.
- **Three Playwright failures left unresolved as a known host limitation, not fixed to green.**
  `auth.spec.ts`'s two longest flows and `monitors.spec.ts`'s full CRUD flow intermittently
  exceed the fixed 30s per-test timeout on this specific sandboxed host under sustained CPU
  contention from the dev-reload file watchers (pre-existing, not a Day 5b regression). Every
  such failure is loud, bounded, and immediate — never a hang — which was the primary
  requirement. Further reducing this would mean either raising the 30s ceiling (explicitly ruled
  out) or restructuring the dev stack's file-watching strategy (out of scope for this session;
  not requested).
- **`frontend/src/components/ui/Button.tsx` exports `buttonVariants`** (previously module-
  private) so `MonitorsListPage`'s "New monitor" link can be styled as a button without a
  nonexistent `asChild` prop.

### Known issues / follow-ups

- The three environment-flaky Playwright tests above are worth revisiting once the dev stack's
  file-watching strategy is reconsidered (e.g. only polling `backend/app`/`frontend/src`
  specifically, already the case, but perhaps a longer poll interval) — not urgent, not a
  correctness bug, not blocking Day 6.
- Real sparklines/latency charts on the monitor list are still a styled "No data yet" skeleton —
  blocked on `CheckResult` rows, which don't exist until Day 7.
- `IncidentsBadge` remains hardcoded to `0` until Day 8.

### Commit block

```bash
git add -A
git commit -m "day 5b: monitor UI, dev CLI, Playwright hardening" -m "$(cat <<'EOF'
- Dev-only CLI (create-user/seed-demo) and matching HTTP backdoor, shared logic in
  dev_fixtures.py; only reachable outside ENV=production
- Monitor UI: list (status pills incl. new `new` variant, usage bar, pause/resume with
  optimistic rollback, check-now, delete) and a shared create/edit form pre-populated from GET;
  both routes lazy-loaded; Overview now shows real per-status counts
- Fixed two real light-theme contrast failures (up-text, degraded-text) found by hand-verifying
  WCAG ratios against all three surfaces in both themes, not just two; added a dedicated `new`
  status token
- Playwright hardening: globalTimeout/per-test/expect timeouts, named deadlines on every
  poll/login helper, workers:1 (measured necessary on this host), bounded navigation retries;
  diagnosed and fixed the prior sessions' silent-hang reports down to host CPU contention from
  dev-reload file-watch polling, not a code hang
- Found and fixed two real bugs the hardened suite exposed: an axe contrast test racing a CSS
  transition, and a rollback test whose own setup starved its assertion's time budget
- Dialed dev rate limits back from an over-aggressive first pass (20x) to ~4x after it broke two
  pytest rate-limit tests via Redis's fail-open breaker
- pytest 208 -> 217, Vitest unchanged at 26, Playwright 23 -> 37 (34 passing + 3 known
  host-contention flakes, documented, never a hang) + a clean 144-screenshot @screenshots run
EOF
)"
```
