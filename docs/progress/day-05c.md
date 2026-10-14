## Day 5c summary (pre-flight before Day 6)

### What was built

**Dev backdoor gating.** `Settings.env` was already `Literal["development", "test", "production"]`
(`backend/app/core/config.py`) — pydantic already rejected any other value, including `"prod"` or
`"Production"`, at `Settings()` construction. That was previously unproven; two regression tests
now cover it. The `/_dev` router mount condition in `backend/app/main.py` changed from
`settings.env != "production"` to `settings.env == "development"`, so it's absent under `"test"`
too, not just `"production"`. `backend/app/dev/router.py`'s docstring updated to match. A new test
proves the router is 404 under `env="test"`, alongside the existing production test.

Confirmed, no code change needed: there is exactly one `Caddyfile` in the repo (dev-only), and it
proxies by generic path prefix (`/api/* /ping/* /healthz /readyz` → `api:8000`) with no
special-casing of `/_dev` at all — gating is enforced entirely at the FastAPI mount layer. A
production Caddy config doesn't exist yet (Day 14 scope), so there's nothing there that could route
`/_dev` even by omission.

**Dev CPU contention.** Measured idle `docker stats --no-stream` before any change (3 samples,
stack already up 21-39h): `api` 5-83%, `runner` 11-82%, `notifier` 23-75% CPU, sustained and bursty.
Root cause, confirmed by reading `watchfiles` 1.3.0's source: force-polling mode re-scans the
watched tree every `poll_delay_ms` (default 300ms), read from the `WATCHFILES_POLL_DELAY_MS` env
var — unset, so both `uvicorn --reload` (which calls `watchfiles.watch()` directly) and the
explicit `watchfiles` CLI used by `runner`/`notifier` were scanning 3-4x a second. Reload-dir
scoping was already correct (api: `--reload-dir /app/app`; runner/notifier: `watchfiles ... /app/
app`) — nothing to change there. Vite polled at the same 300ms cadence with no `ignored` patterns,
watching the whole bind-mounted `frontend/` tree (`frontend/tests/screenshots` alone has 188
files).

Fix: `WATCHFILES_POLL_DELAY_MS=1000` added to `api`/`runner`/`notifier` in
`compose.override.yaml`; Vite's polling `interval` raised 300ms → 1000ms with
`ignored: ['**/node_modules/**', '**/dist/**', '**/tests/screenshots/**', '**/test-results/**']`
added in `frontend/vite.config.ts`. The specific values (1000ms, that ignore list) are a judgment
call matching the qualitative ask, not numbers Oryn specified — see Deviations.

### Files changed (grouped by area)

- **Dev backdoor gating**: `backend/app/main.py` (mount condition), `backend/app/dev/router.py`
  (docstring), `backend/tests/dev/test_dev_router.py` (new `env="test"` test, shared
  `_assert_dev_router_absent` helper), `backend/tests/test_config_guard.py` (two new
  invalid-`env` tests)
- **Dev CPU contention**: `compose.override.yaml` (`WATCHFILES_POLL_DELAY_MS` on api/runner/
  notifier), `frontend/vite.config.ts` (poll interval + `ignored`)
- **Docs**: `docs/progress/day-05c.md` (this file)

### Migrations

None.

### Tests: 217 -> 220 (pytest) · Playwright 34/37 -> 34/37 (unchanged, see below)

**pytest**: 220 passed, 1 deselected (`timeout 300 docker compose exec api pytest -q`,
213.48s). +3 over the 217 baseline: two `Settings(env=...)` rejection tests
(`test_rejects_unknown_env_value`, `test_rejects_wrong_case_env_value`) and one dev-router test
(`test_dev_router_not_mounted_under_test_env`).

**Playwright** (`timeout 1200 docker compose --profile tools run --rm pw-tests npx playwright
test --grep-invert "@screenshots"`): **34 passed, 3 failed — same three tests as Day 5b**
(`auth.spec.ts`: "signup -> verify -> login -> navbar -> logout", "an unverified account sees the
resend banner", "forgot -> reset -> login with the new password"), still `workers: 1`. The target
of 37/37 was **not** reached. Per instruction, stopping here rather than running another tuning
pass.

This is a real finding, not a shrug: idle CPU contention on `api`/`runner`/`notifier` dropped from
a sustained 60-85% range to ~1-5% (measured below) after the fix, yet these exact three tests still
fail the same way. All three are the only specs in the default suite that drive a **real email
round-trip through Mailpit** (verify-link / reset-link lookup via `helpers/mailpit.ts`), unlike
every passing spec. That's a different contention/latency source than file-watcher CPU — Mailpit
polling latency, not dev-server reload scanning — and wasn't touched by this pre-flight's scope.
Recommend treating this as the next thing to investigate before deciding on the WSL/no-polling
move, since the CPU fix measurably worked but didn't change this specific failure mode.

### Live verification (commands + real output)

Rebuild/restart to pick up config changes:
```bash
timeout 300 docker compose up -d --build
```
All 9 services recreated and healthy; `WATCHFILES_POLL_DELAY_MS=1000` confirmed present via
`docker inspect` on `api`/`runner`/`notifier`.

**CPU, before** (stack idle, already up 21-39h, 3 samples a few seconds apart):
```
api        5.47% / 73.26% / 82.63%
runner    11.06% / 65.15% / 81.77%
notifier  23.09% / 60.65% / 75.15%
chaos      0.18% / 0.20% / 0.24%   (one earlier one-off 101.86% sample, not reproduced)
db/caddy/redis/mailpit: all ~0-15%, no sustained load
```

**CPU, after** (post-restart, waited ~45s for migrations/warmup to clear, 5 samples a few seconds
apart):
```
api        0.79% / 0.96% / 2.64% / 3.40% / 4.19%
runner     0.73% / 0.84% / 2.00% / 2.51% / 3.46%
notifier   0.84% / 2.16% / 5.43% / 27.42% / 33.43%   (one/two brief blips, still well under before)
chaos      0.13% - 0.19% in 3 of 5 samples, 74-81% in the other 2 (see Deviations — unrelated,
           out of scope, no --reload, pre-existing intermittent behavior)
```

Backend — `timeout 300 docker compose exec api pytest -q`:
```
220 passed, 1 deselected in 213.48s (0:03:33)
```

Playwright default suite — `timeout 1200 docker compose --profile tools run --rm pw-tests npx
playwright test --grep-invert "@screenshots"`:
```
34 passed, 3 failed (auth.spec.ts x3 — see Tests section)
Wall clock: 14.0m
```

Manual sanity check:
```bash
docker compose exec api python -c "
from app.core.config import Settings
Settings(env='Production', database_url='x')
"
# -> pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
```

### Deviations from SRS / CLAUDE.md

- **Picked 1000ms as the new poll interval/delay, and a specific ignore-glob list, without a
  number from Oryn.** The instruction said "longer poll interval" and named the four paths to
  ignore; 1000ms (up from 300ms) is a 3-4x reduction in scan frequency chosen as a reasonable
  first step, not a value with a specific target. If Mailpit latency (see Tests) turns out to be
  the real blocker rather than this, this value may need no further tuning at all.
- **Goal of 37/37 Playwright not reached** — stopping and reporting per instruction rather than
  running another round. The three failures are identical to Day 5b's, and now have a narrower,
  more specific candidate cause (Mailpit round-trip, not file-watch CPU) than before.
- **Chaos's intermittent CPU spikes (0.2% to 80%+) left uninvestigated** — out of this pre-flight's
  stated scope (chaos has no `--reload`/file-watch polling at all, so it isn't a "dev CPU
  contention" item as defined), but flagged below as worth a look.

### Known issues / follow-ups

- The 3 `auth.spec.ts` failures persist after the CPU fix; next step is probably instrumenting
  `helpers/mailpit.ts`'s polling (timing, retry count) rather than further tuning file-watch
  intervals.
- Chaos's CPU is bursty (0.2% to 80%+) with no apparent trigger (no requests were made during
  measurement) — worth a quick look, not urgent, not blocking Day 6.
- Decision point for Oryn per the original instruction: move the repo into the WSL filesystem and
  disable polling entirely, now that file-watch polling is confirmed as *a* contention source but
  not the cause of the 3 remaining failures.

### Commit block

```bash
git add -A
git commit -m "day 5c: dev backdoor gating, dev CPU contention" -m "$(cat <<'EOF'
- /_dev router now mounts only when ENV=development (was: != production), so it's also absent
  under ENV=test; docstring and tests updated to match
- Added regression tests proving Settings.env's Literal already rejects "prod"/"Production" at
  construction (no production code change needed there)
- Confirmed the dev Caddyfile has no /_dev-specific routing and no production Caddy config exists
  yet -- dev-backdoor enforcement is entirely at the FastAPI mount layer
- Root-caused Day 5b's documented CPU-contention flakiness to watchfiles' default 300ms
  force-polling scan cadence (api/runner/notifier) and Vite's matching 300ms poll with no ignore
  patterns; raised both to 1000ms and added ignores for node_modules/dist/screenshots/test-results
- Idle CPU on api/runner/notifier dropped from a sustained 60-85% range to ~1-5%, but the same 3
  auth.spec.ts Playwright tests (the only specs with a real Mailpit email round-trip) still fail
  at 34/37 -- a different, more specific lead than before, not chased further this session per
  instruction
- pytest 217 -> 220 (3 new tests), Playwright unchanged at 34/37 (see day-05c.md for the full
  before/after CPU numbers and reasoning)
EOF
)"
```
