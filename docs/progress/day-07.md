## Day 7 summary

### What was built

- **Guarded network backend** (`app/engine/guarded_backend.py`): a custom `httpcore.AsyncNetworkBackend`
  (`GuardedBackend`) that enforces the Day 4 SSRF policy at connect time, for every connection
  and every redirect hop. `connect_tcp` validates port policy, then either the IP literal
  directly or every address a DNS resolution returns (all-or-nothing — one denied address in a
  mixed record set blocks the whole connect), then dials the *validated IP*, never the hostname
  again. That last step is the entire DNS-rebinding defense: the address checked is the exact
  address dialed. `BlockedAddressError`/`DnsResolutionError` are deliberately not httpcore
  exception subclasses, so httpx's exception-mapping layer never rewraps them. A `_TimedStream`
  wrapper records `dns_ms`/`connect_ms`/`tls_ms` without touching TLS correctness itself.
- **The real HTTP probe** (`app/engine/http_probe.py`): `HttpProbe.check()` builds a fresh
  `GuardedBackend` + `httpcore.AsyncConnectionPool` + `httpx.AsyncClient` per check (no pooling
  across checks), wired into httpx via `transport._pool = httpcore.AsyncConnectionPool(...)` —
  the real seam `AsyncHTTPTransport.__init__` itself uses, verified by reading its source.
  `trust_env=False`, max 3 redirects, honest User-Agent, 64 KB body cap via streaming +
  early-close, an authoritative `asyncio.timeout(monitor.timeout_seconds)` wall-clock deadline
  (httpx's own read-timeout resets on every byte, which a trickling server could exploit to
  never trip it — the wall-clock guard closes that gap). Classifies every outcome into
  `error_kind` (`http_status`/`timeout`/`connection`/`dns`/`tls`/`redirects`/`blocked`/`None`),
  with TLS-vs-plain-connection-failure distinguished by walking the exception's `__cause__`
  *and* `__context__` chain for an `ssl.SSLError` (see Deviations — the context fallback was a
  real fix, not a hypothetical).
- **`error_kind` column** on `check_results` (migration `0009`, CHECK-constrained to the fixed
  vocabulary), plumbed through `write_result`'s CTE and a new `error_kind: str | None = None`
  field on `ProbeResult` (additive, `StubProbe` untouched).
- **Per-host politeness cap** (`app/engine/host_cap.py`): `check_host_cap` wraps
  `FailOpenRedis.incr_with_ttl` directly (not the HTTP-coupled `enforce_rate_limit`), called
  from `runner.py::_run_one` before the semaphore is even acquired. Over cap → skip the check
  entirely this cycle (no probe call, no `write_result`, no row) — a capped host is evidence of
  Cronos's own load, not the target's health, so writing a result would be dishonest telemetry.
  Redis down → fails open (never skips).
- **Runner wiring**: `PROBE_KIND` widened to `Literal["stub", "http"]`, default now `"http"`;
  dispatch extracted into `_build_default_probe()` (unit-testable without the tick loop);
  `_RunnerContext` gained a `redis: FailOpenRedis` field, closed on shutdown alongside the
  engine.
- **SSRF-policy helper renames**: `_parse_ip_literal`/`_is_denied_ip`/`_unwrap_ipv4_mapped`/`_resolve`
  → `parse_ip_literal`/`is_denied_ip`/`unwrap_ipv4_mapped`/`resolve` (public names), since
  `guarded_backend.py` is now a real cross-module consumer, not an internal detail.
  `ssrf_policy.py` itself is otherwise unchanged — Day 4's rules are reused, not duplicated.
- **Chaos target** (`chaos/app/main.py`): added `flap` (alternates up/`status_code` every N
  requests to a path), `hang` (accepts, never responds — bounded at 300s plus polling for
  client disconnect, so repeated hang checks never accumulate stuck server-side tasks),
  `redirect` (configurable target + status; a loop is just two paths pointing at each other),
  `big` (streamed in fixed 64 KB chunks, never materialized whole), and `tls_bad` (a second,
  same-app `uvicorn.Server` on port 8443 with a self-signed **and** already-expired certificate,
  generated once at startup via `cryptography` — new chaos-only dependency). Also added
  `/whoami` (User-Agent + client source port, for proving fresh connections) and a minimal
  webhook-receiver stub (`POST /webhook` logs what arrived and returns a configurable status;
  `GET /_webhook/_log` reads it back) — full HMAC verification deferred to Day 9 with an
  explicit TODO, since nothing sends signed webhooks yet.
- **New dependencies**, flagged per CLAUDE.md before adding: `cryptography==50.0.2`
  (`chaos/pyproject.toml` only); `httpcore==1.0.9` and `certifi==2026.7.22` promoted from
  implicit transitive dependencies to explicit pins in `backend/pyproject.toml` (application
  code now imports `httpcore` directly and builds its own SSL context from `certifi` rather than
  httpx's private `create_ssl_context` helper).

### Files changed (grouped by area)

**Engine / probe (backend)**
- `backend/app/engine/guarded_backend.py` (new) — the SSRF-enforcing httpcore backend
- `backend/app/engine/http_probe.py` (new) — `HttpProbe`
- `backend/app/engine/host_cap.py` (new) — per-host politeness cap
- `backend/app/engine/probe.py` — `ProbeResult.error_kind` field
- `backend/app/engine/results.py` — `error_kind` in the write CTE
- `backend/app/engine/runner.py` — `PROBE_KIND` dispatch, Redis wiring, host-cap check
- `backend/app/engine/ssrf_policy.py` — helper renames (public, no behavior change)

**Schema**
- `backend/alembic/versions/0009_check_result_error_kind.py` (new)
- `backend/app/monitors/models.py` — `CheckResult.error_kind` + CHECK constraint

**Config / dependencies**
- `backend/app/core/config.py` — `probe_kind` widened + default flip, new `probe_*` settings
- `backend/pyproject.toml`, `backend/uv.lock` — explicit `httpcore`/`certifi` pins

**Chaos service**
- `chaos/app/main.py` — new modes, `/whoami`, webhook stub, second TLS listener
- `chaos/app/tls_bad_cert.py` (new) — self-signed + expired cert generation
- `chaos/pyproject.toml`, `chaos/uv.lock` — `cryptography` dependency
- `chaos/Dockerfile` — `EXPOSE 8443`
- `chaos/healthcheck_http.py` — also probes the TLS-bad listener

**Tests**
- New: `test_guarded_backend.py`, `test_http_probe_seam.py`, `test_error_classification.py`,
  `test_http_probe_chaos.py`, `test_host_cap.py`
- Updated: `test_config_guard.py` (probe_kind default flip), `tests/dev/test_dev_router.py`
  (restores the production-dev-router test per Day 6's own TODO), `tests/engine/test_runner.py`
  (Redis wiring in `_RunnerContext`, dispatch tests, host-cap-skip test), `test_ssrf_policy.py`
  (renamed monkeypatch targets)

### Migrations

- **`0009_check_result_error_kind`**: adds `check_results.error_kind` (nullable text), CHECK-constrained
  to `('http_status', 'timeout', 'connection', 'dns', 'tls', 'redirects', 'blocked')`. Verified
  live: `\d check_results` shows the column and `ck_check_results_error_kind_allowed`; `alembic
  check` reports no drift between the ORM model and migration state; the `migration`-marked
  round-trip test (`downgrade base -> upgrade head`) passes.

### Tests: 245 -> 295 (pytest, 1 deselected both times)

50 net new pytest tests: 13 in `test_guarded_backend.py` (fake-resolver/fake-connector unit
tests — decimal/octal/hex IP forms, IPv6 loopback + mapped, mixed public/private record sets
block entirely, DNS-rebinding proof, SNI-hostname proof, timing capture), 1 in
`test_http_probe_seam.py` (the real-transport canary), 11 in `test_error_classification.py`
(exception → `error_kind` mapping, including the `__context__`-fallback case found live), 9 in
`test_http_probe_chaos.py` (live chaos integration — up/down/slow/hang/flap/redirect/redirect-loop/big/tls-bad),
3 in `test_host_cap.py`, plus 1 renamed + 1 added in `test_config_guard.py`, 1 renamed + 1 added
in `test_dev_router.py`, 3 added in `test_runner.py` (`_build_default_probe` dispatch ×2,
host-cap-skip). No tests were removed; `test_ssrf_policy.py`'s count is unchanged (only its
monkeypatch targets were renamed).

Vitest: 26 -> 26 (unchanged; Day 7 touched no frontend code). Playwright: not re-run — zero UI
changes this day, so there is nothing new to screenshot; still 37/37 as of Day 6.

### Live verification (commands + real output)

All run against the live Compose stack (`docker compose up -d --build api chaos`, then
`docker compose up -d` to recreate `runner`/`notifier`/`migrate` from the rebuilt image).

**1. Schema**: `docker compose exec api alembic upgrade head` → `Running upgrade 0008 -> 0009,
check_results.error_kind`. `\d check_results` confirmed the column + constraint (see Migrations
above).

**2. `https://example.com` monitor, full timings** (one `check_results` row, pasted verbatim):
```
monitor_id      | f9d095ce-0881-42e3-9b82-4e53fa29c1ff
checked_at      | 2026-10-15 12:06:05.767695+00
scheduled_for   | 2026-10-15 12:06:04.092281+00
is_up           | t
status_code     | 200
response_time_ms| 142
timings         | {"dns_ms": 12.36, "tls_ms": 46.39, "ttfb_ms": 138.48, "total_ms": 141.98, "connect_ms": 29.99}
error           |
error_kind      |
```

**3. One monitor per chaos mode**, after ~2+ cycles each (30s interval), queried from
`check_results` joined to `monitors`:

| Monitor | is_up | status_code | error_kind | response_time_ms (range) |
|---|---|---|---|---|
| chaos-up | true | 200 | — | 1517–2198 |
| chaos-down (503) | false | 503 | http_status | 445–2343 |
| chaos-slow (500ms delay) | true | 200 | — | 577–2094 |
| chaos-hang (timeout=3s) | false | — | timeout | 3004–3014 |
| chaos-redirect-metadata (→169.254.169.254) | false | — | blocked | 1015–1936 |
| chaos-redirect-db (→db:5432) | false | — | blocked | 800–1718 |
| chaos-redirect-loop | false | — | redirects | 647–1938 |
| chaos-big (20 MB body, 64 KB cap) | true | 200 | — | 414–1616 |
| chaos-flap | alternates true/false | 200/503 | —/http_status | 289–1355 |
| chaos-tls-bad (self-signed+expired, :8443) | false | — | tls | 86–1179 |

(Response times run a few hundred ms to ~2s higher than a single isolated check because all ten
monitors plus later an 80-monitor cap-saturation batch were deliberately hammering the same
`chaos` host concurrently — see Known issues.)

**4. SQL-inserted metadata monitor** (`http://169.254.169.254/latest/meta-data`, inserted
directly via `psql`, never through the API's save-time validation): `is_up=false,
error_kind=blocked`, response times 4–1863ms — proves the connect-time guard is the real,
independent enforcement point, not just save-time UX.

**5. Fresh connections**: three manual `/whoami` requests through the real guarded-transport
construction returned three different client source ports (`42040`, `42046`, `42058`) with the
correct `User-Agent` echoed back — confirms no connection reuse across checks.

**6. Big body, bounded memory**: `docker stats` snapshots taken every ~14s while the big-body
and hang monitors ran showed `cronos-runner-1` holding steady at 118–127 MiB and
`cronos-chaos-1` at ~44–45 MiB throughout, despite one monitor streaming a 20 MB body on every
cycle — the 64 KB read-then-discard cap is real, not just correct on paper.

**7. Per-host politeness cap**: inserted 80 monitors against `chaos` (shared with the 10
chaos-mode monitors already running — demonstrating the cap is genuinely global-per-host, not
per-monitor). After one ~70s wait: 55 of the new 80 had a `check_results` row;
`host_cap_skipped` appeared in runner logs for the rest (131 occurrences across both batches).
`docker compose stop redis` at `12:08:44`, confirmed via the real `redis_unavailable` log line
at `12:08:43.89` (`"error": "Connection closed by server."`) — the *last* `host_cap_skipped`
event in the whole session occurred at `12:08:39.84`, strictly before the outage. In the 35s
after the stop, the cap-test monitors' row count grew from 55 to 135 (80 more, i.e. every
due check succeeded) with zero further skips — fail-open confirmed. `docker compose start
redis` → `redis_recovered` logged within 5s; the 80 cap-test monitors were then deleted.

**8. Hang-mode resource-leak check**: paused every other live-acceptance monitor, captured
baseline FDs (`docker compose exec runner sh -c "ls /proc/1/fd | wc -l"` → 6), inserted 50
monitors all hitting the bounded `hang` mode (`timeout_seconds=2`), and let two full 30s cycles
run (101 `check_results` rows total — some individual checks were themselves host-cap-skipped
mid-run, expected given 50 hang checks to one host in under a minute). FD count after both waves:
3, then 4 — flat, no growth. `docker stats` showed `cronos-runner-1` steady at ~122 MiB and
`cronos-chaos-1` steady at ~44 MiB with 5 PIDs throughout — the bounded/disconnect-aware hang
handler on the chaos side isn't accumulating stuck tasks either.

**9. Test suite**: pytest 245 → 295 (1 deselected both times), migration round-trip passed,
`alembic check` reported no drift, Vitest 26 → 26. No CRLF in any new/changed file (checked
directly).

All live-acceptance test monitors and the scratch account were deleted afterward
(`DELETE FROM accounts WHERE id = '11111111-1111-1111-1111-111111111111'`, cascading); a final
pytest re-run after all the Redis stop/start and container manipulation still showed 295
passed, confirming the stack was left in a healthy, unaffected state.

### Deviations from SRS / CLAUDE.md

- **SSL context construction**: built from `ssl.create_default_context(cafile=certifi.where())`
  directly rather than httpx's private `httpx._config.create_ssl_context` — avoids relying on a
  second private httpx internal on top of the already-necessary `transport._pool` swap. Flagged
  and approved during planning; `certifi` added as an explicit dependency as a result.
- **TLS-failure classification walks `__context__`, not just `__cause__`** — found live, not
  anticipated in the plan. Reading httpcore's source suggested a clean two-level `__cause__`
  chain (`httpx.ConnectError` ← `httpcore.ConnectError` ← `ssl.SSLError`, each via `raise ... from
  exc`). Driving a real handshake against the chaos `tls_bad` listener showed the actual chain is
  `httpcore.ConnectError.__cause__ = None`, `httpcore.ConnectError.__context__ = ssl.SSLError` —
  httpcore's `Trace` instrumentation re-raises with `from None` at one hop, clearing `__cause__`
  while Python still records `__context__` automatically. `_is_tls_failure` now walks
  `cause or context` at every hop; a new unit test (`test_is_tls_failure_falls_back_to_context_when_cause_is_suppressed`)
  pins this down going forward. Everything else in the guarded-backend/httpx-seam design matched
  the plan's source-reading exactly (the `transport._pool` swap, `connect_tcp`/`start_tls`
  receiving the original hostname, `AsyncConnectionPool`'s constructor signature).
- **No `ports:` mapping added for chaos's TLS-bad listener** — container-to-container
  reachability on the shared `default` network works for any bound port regardless of `EXPOSE`;
  verified rather than assumed (chaos already published nothing for its plain port either).
  `EXPOSE 8443` was added to the Dockerfile as documentation only.
- **Webhook receiver is a minimal stub**, not full HMAC verification — confirmed with Oryn
  during planning, since nothing in the codebase sends a signed webhook yet (Day 9). A `DAY 9
  TODO` comment marks exactly where real verification lands.

### Known issues / follow-ups

- Response times for monitors sharing the `chaos` host during this session's live-acceptance
  run were noticeably inflated (hundreds of ms to ~2s) compared to an isolated check (~100–300ms
  for the same modes) — self-inflicted by running 10–90+ monitors against one chaos container
  concurrently for test purposes; not a latency regression in the probe itself.
  `chaos-redirect-metadata`/`chaos-redirect-db` in particular pay a real network round-trip to
  chaos for the initial 302 before the blocked hop, which is correct behavior, just not
  "near-instant" the way a pure connect-time block is.
  - **Why**: deliberate test-load, not a code issue.
  - **Follow-up**: none needed; noted for whoever reads these numbers later so they aren't
    mistaken for steady-state probe latency.
- The chaos target's `tls_bad` mode runs a second `uvicorn.Server` in-process via
  `lifespan="off"` and a monkeypatched `capture_signals` to avoid re-entering the app's own
  lifespan and to avoid two `Server`s fighting over SIGINT/SIGTERM. This works and was verified
  live, but is inherently a bit fragile against future uvicorn upgrades changing either of those
  internals. No test currently guards this specific wiring beyond the live TLS-handshake proof
  (`test_tls_bad_mode_reports_tls_error_kind`) and the container staying healthy.
- Day 6's known `asyncpg InternalClientError` risk under server-initiated disconnect during a DB
  restart was not revisited this day (not in scope); still worth a dedicated look before the
  Hetzner deploy (Day 14).

### Commit block

```bash
git add -A
git commit -m "day 7: real HTTP probe, connect-time SSRF guard, error classification, host cap" -m "$(cat <<'EOF'
- Guarded httpcore network backend (app/engine/guarded_backend.py) enforcing the Day 4 SSRF
  policy at connect time, for every connection and redirect hop; DNS-rebinding-proof (dials the
  validated IP, never re-resolves the hostname); all-or-nothing on mixed public/private record
  sets.
- Real HttpProbe (app/engine/http_probe.py) behind the unchanged Probe protocol: fresh
  connection per check, 64 KB body cap, phase timings, wall-clock deadline, error_kind
  classification (http_status/timeout/connection/dns/tls/redirects/blocked).
- Migration 0009: check_results.error_kind (CHECK-constrained), plumbed through write_result.
- Per-host politeness cap (app/engine/host_cap.py) via FailOpenRedis, checked in runner.py
  before the probe runs; fails open on Redis outage.
- PROBE_KIND now Literal["stub","http"], defaults to "http" -- production starts cleanly with
  zero config; stub remains available as an explicit, refused-in-production override.
- ssrf_policy.py helpers made public (parse_ip_literal/is_denied_ip/unwrap_ipv4_mapped/resolve)
  since guarded_backend.py is now a real cross-module consumer.
- Chaos target gains flap/hang/redirect/big/tls_bad modes, /whoami, and a minimal webhook-
  receiver stub (full HMAC verification deferred to Day 9).
- New deps: cryptography (chaos only); httpcore and certifi promoted to explicit backend pins.
- Tests: 245 -> 295 (pytest), Vitest unchanged at 26, Playwright unchanged at 37/37 (no UI
  changes this day).
EOF
)"
```
