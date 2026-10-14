# CLAUDE.md — Cronos

Cronos is Project 2 of Oryn's 100-day plan: uptime monitoring for HTTP endpoints, heartbeat
(dead man's switch) monitoring for cron jobs, incidents, alerts (email + signed webhooks), and
status pages. The source of truth for requirements is the **Cronos SRS** (revision 2). If this
file and the SRS disagree, stop and ask — do not pick one silently.

The product promise: **Cronos must be more reliable than what it watches, and must never blame
a user's service for Cronos's own failure.** When in doubt, choose the option that keeps that
promise.

---

## Workflow (how we work)

1. Every day starts in **plan mode**. Produce a plan against the day's acceptance criteria, wait
   for approval, then build.
2. **Never run state-changing git commands** (`commit`, `push`, `reset`, `rebase`, `checkout -b`,
   `stash`, `merge`, `tag`). Read-only git (`status`, `diff`, `log`) is fine. Oryn commits manually.
3. Verify against the **running Compose stack**, not just tests. Show the commands you ran and
   their real output.
4. If you deviate from the SRS or this file, say so explicitly in the summary with the reason.
5. Do not add dependencies beyond the stack below without listing them in the plan first.

### End-of-day summary (required format)

Write the summary to `docs/progress/day-NN.md` (zero-padded, e.g. `day-01.md`) **before**
presenting it, and present the same text in chat. The progress file is part of the day's commit.
If a review round changes anything, update the file to match before the commit block is used.

```
## Day N summary
### What was built
### Files changed (grouped by area)
### Migrations (name + what they do)
### Tests: <before> -> <after> (explain any decrease)
### Live verification (commands + real output, incl. Mailpit/Playwright evidence)
### Deviations from SRS / CLAUDE.md
### Known issues / follow-ups
### Commit block
```

The commit block is copy-paste-ready for Oryn's terminal:

```bash
git add -A
git commit -m "day N: <concise summary>" -m "<bullet details>"
```

---

## Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0 (async, asyncpg), Alembic,
  Pydantic v2, httpx + custom httpcore network backend, argon2-cffi, structlog (JSON logs), Sentry.
- **Data:** PostgreSQL 16 (source of truth, clock and queue). Redis 7 (**non-critical**: rate
  limits and caches only).
- **Frontend:** React + Vite + TypeScript + Tailwind, Radix-based components (shadcn/ui pattern),
  lucide-react, Motion (formerly Framer Motion), TanStack Query, React Router, Recharts.
- **Edge:** Caddy (TLS, serves SPA, proxies `/api` and `/ping`) — one origin, no CORS.
- **Dev tools:** Docker Compose, Mailpit, Playwright, pytest + pytest-asyncio, Vitest, the
  `chaos` target service.
- Pin exact versions. Pin base Docker images by digest.

## Processes

| Service  | Entrypoint                    | Job |
|----------|-------------------------------|-----|
| api      | `uvicorn app.main:app`        | Auth, CRUD, `/ping`, public status snapshots, `api_alive` upsert every 10s |
| runner   | `python -m app.engine.runner` | Claim due monitors, probe, record, incidents, outbox rows, maintenance jobs |
| notifier | `python -m app.notifier`      | Drain the outbox, deliver email/webhooks, retries |
| migrate  | `alembic upgrade head`        | One-shot, runs before the others |

## Repo layout

```
cronos/
  CLAUDE.md
  compose.yaml            # prod-shaped services
  compose.override.yaml   # dev: mailpit, chaos, vite dev server, ports
  .env.example
  caddy/Caddyfile
  backend/
    pyproject.toml
    alembic/
    app/
      main.py             # API app factory
      core/               # config, db, logging, clock, security, errors
      auth/  accounts/  plans/
      monitors/  heartbeats/  incidents/  notifications/  status_pages/
      engine/             # runner, claim, probe/, ssrf_guard, canary, sweep, maintenance
      notifier/           # worker, email, webhook, signing
    tests/
  frontend/
    design/tokens.md      # extracted from the portfolio, approved by Oryn
    src/
      app/                # shell, router, floating navbar, providers
      components/ui/      # primitives
      components/motion/  # shared motion tokens and wrappers
      features/<area>/    # monitors, heartbeats, incidents, channels, status-pages, settings
      pages/public-status/   # separately code-split, minimal bundle
      lib/api/            # typed client, error shape
  chaos/                  # tiny misbehaving-website service + fake webhook receiver
  notebooks/              # anomaly backtests (pandas lives here only)
  scripts/                # backup, restore, ops helpers
```

---

## Non-negotiables

### Engine and reliability
- **Postgres is the clock.** All time comparisons use DB `now()`. App code that needs "now" for
  logic uses the injectable clock in `core/clock.py` (tests freeze it). Never `datetime.now()` in
  business logic.
- **The check and alert path depends only on Postgres.** Redis failure must never stop a check,
  an incident or an alert. All Redis use is fail-open with a circuit breaker (Project 1 lesson).
- **Claims:** one short transaction with `FOR UPDATE SKIP LOCKED`, `LIMIT = free slots`,
  advancing `next_check_at` (cadence-preserving; skip missed slots). **No DB lock or open
  transaction during an HTTP request.**
- "Check now" = set `next_check_at = now()`. There is no second execution path.
- **Confirmation:** first failure → re-check in 30s; incident opens at `confirm_threshold`.
  Counters change only via atomic `UPDATE ... RETURNING`.
- **One open incident per subject**, enforced by a partial unique index; insert with
  `ON CONFLICT DO NOTHING`. `started_at` = first failing check.
- **Canaries:** when ≥2 of 3 canaries fail, results are `suppressed=true`, counters do not move,
  no incidents open, and the watchdog ping stops.
- **Heartbeats:** `new` never alerts. Deadline = `greatest(last_ping_at, ingest_recovered_at) +
  period + grace`. The sweep is a conditional `UPDATE ... RETURNING` (safe if run twice).
- **Outbox:** notification rows are written in the **same transaction** as the incident change.
  Nothing sends email/webhooks inline from api or runner. *(Exception, Day 3: auth emails —
  verify, already-registered notice, reset — send via a FastAPI `BackgroundTask` after the
  response, not through the outbox; a lost auth email is recoverable via resend, unlike an
  incident alert.)*
- Flapping and alert caps live in Postgres, not Redis.
- Maintenance jobs run under `pg_try_advisory_lock` (one runner at a time).

### Security
- **SSRF guard is enforced at connect time** inside the custom httpcore network backend, for
  monitors **and** webhooks. Save-time validation is UX only. Reject any non-global address
  (unwrap IPv4-mapped IPv6), metadata 169.254.169.254, 100.64/10, 0/8; http/https only; port
  policy per SRS §13; `trust_env=False`; monitors max 3 redirects, webhooks none.
- The dev-only `SSRF_ALLOW_HOSTS` (lets the runner reach `chaos`) must make the app **refuse to
  start** when `ENV=production`.
- Fresh connection per check (no pooling); read ≤64 KB of body then discard; never store or log
  response bodies.
- Monitors are GET/HEAD only. No custom headers or bodies in v1.
- Sessions: random token in httpOnly/Secure/SameSite=Lax cookie; DB stores only its SHA-256.
  CSRF double-submit header on every state-changing route. Passwords: argon2.
- **When Day 4 adds API keys:** if `Authorization` is present, authenticate only by API key; an
  invalid key is a 401, never a silent fallback to the session cookie.
- API keys: shown once, stored hashed, looked up by prefix, scoped, revocable.
- Webhook secrets encrypted at rest. Signature: `v1=HMAC-SHA256(secret, timestamp + "." + body)`.
- `/ping/*` always returns 200 (no slug enumeration). Never log slugs, tokens, or raw IPs (hash IPs).
- Email must be verified before monitors/heartbeats run.

### Data
- UUID PKs, except `check_result` and `heartbeat_ping` (bigint).
- Polymorphic references = two nullable FKs + CHECK exactly-one. No uuid arrays for relations.
- Charts read `latency_hourly`, never raw `check_result` beyond the last 24h.
- `usage_event` is written by the daily rollup, never per check.
- Every model change ships with an Alembic migration; never edit an applied migration.

### Plans / payment seam
- **v1 has exactly one plan: `launch`.** No billing, no tiers, no feature gating, no upgrade
  prompts. Do not build `free`/`pro` plans, Stripe integration or paywalls in v1.
- Launch limits exist only for cost and abuse protection (SRS §12): 15 monitors, 15 heartbeats,
  120s minimum interval, 3 status pages (private allowed), 14 days raw / 90 days hourly
  retention, 50 alert emails and 500 webhooks per day.
- The seam still exists from day one: all limits come from `PLANS` through the `check_limit()`
  dependency. No hard-coded limits anywhere else. `account.plan` defaults to `"launch"`.
- Users must be told the limits are launch-period limits: notice at signup, a dismissible
  Settings banner, and a `/pricing` page (SRS §12 wording). When Cronos monetises they choose a
  paid plan or move to free, with ≥30 days' notice.
- Implement the downgrade rule as a tested function now (pause newest over-limit subjects,
  raise intervals, unpublish private pages, delete nothing), even though only v2 will call it.

### API conventions
- JSON under `/api/v1`; errors always `{"error": {"code", "message", "field?"}}`.
- Every PATCH endpoint has a test that PATCHes, then GETs, and asserts the stored values round-trip
  (the API equivalent of Project 1's "GET the edit page" rule). The matching UI form must
  pre-populate from the GET — verified in Playwright.

---

## UI non-negotiables

The UI must feel futuristic and live: dark and light themes, glowing status colour, purposeful
motion. It draws on Oryn's portfolio (https://www.bonyaransom.me/). See SRS §9.

- **Design tokens** live in `frontend/design/tokens.md` and as CSS variables / Tailwind theme. No
  ad-hoc hex colours, font sizes or durations in components.
- **Identity:** Syne (display), Outfit (interface), DM Mono (body copy and all numbers, tabular
  figures), 2px corners on surfaces/cards/inputs, the extracted glow recipe.
- **Colour roles:** green `#00C853` = up/healthy + brand glow, used ONLY for status and brand
  marks. A separate cool interactive accent for buttons, links, focus rings, selected states and
  the navbar active pill. Status = up green / down red / degraded amber / paused grey, each with
  a dot/glow variant and a text-safe variant. Status always pairs colour with an icon or label.
- **Two first-class themes:** dark and light. Default follows `prefers-color-scheme`; a toggle
  (Account menu + command palette) overrides it, persisted in localStorage. Every token has a dark
  and a light value; light uses a darker text-safe green and replaces glows with tinted rings /
  soft shadows. An inline script in `index.html` sets the theme before first paint (no flash).
  Public status pages follow the viewer's OS theme.
- **Floating bottom navbar** (signature):
  - `position: fixed`, centered, `bottom: calc(1rem + env(safe-area-inset-bottom))`,
    `width: fit-content`, `max-width: calc(100vw - 2rem)`. **Never edge-to-edge.**
  - Rounded-full glass capsule: translucent surface, backdrop blur, 1px hairline border, soft
    shadow, comfortable padding.
  - Items: Overview, Monitors, Heartbeats, Incidents, Status pages | Search (⌘K), Account.
  - Active pill slides between items via Motion shared layout (`layoutId`).
  - Incidents shows a live count badge that pulses while incidents are open.
  - Mobile: icons only, active item expands to show its label.
  - Subtly compacts on scroll down, restores on scroll up; never hides.
  - Page content reserves bottom padding (bar height + 2rem).
  - `<nav>` landmark, `aria-current="page"`, visible focus rings, keyboard reachable.
  - Not rendered on public status pages.
- **Motion:** shared tokens (150/250/400ms, one spring, one ease) in `components/motion/`. Animate
  only `transform` and `opacity`. No layout shift. Skeleton shimmer, never spinners.
- **`prefers-reduced-motion`** disables non-essential motion; the UI must still look finished.
- Portfolio motifs: oversized headings ending in a full stop ("Monitors."), small eyebrow line
  above headings, status pills with a dot.
- Signature components: status orb, ECG heartbeat line, latency sparklines, 90-day uptime bars,
  incident timeline, command palette.
- Public status page is code-split: no chart library, **< 100 KB gzipped JS**.
- WCAG AA contrast in both themes. Every page gets Playwright screenshots at 375 / 768 / 1440px ×
  dark / light × reduced motion on and off.

---

## Testing

- pytest-asyncio against **real Postgres** (never SQLite).
- Use the injectable clock for confirmation, flap, sweep and suppression tests.
- Required engine tests: two runners × 200 due monitors → exactly 200 results; `kill -9`
  recovery; partial unique index blocks duplicate incidents.
- Required SSRF tests: decimal/octal IPs, IPv6 loopback, DNS → 127.0.0.1, 302 → metadata,
  mixed public/private records, webhook to private address.
- Use the `chaos` service (SRS §15) for live acceptance. Use Mailpit for email evidence.
- Report the test count before → after every day.
- Every potentially blocking command runs under a wall-clock `timeout`, and every poll loop has
  a deadline (Day 5b: a silent Playwright hang cost two sessions over an hour, once 13 hours).

## Common commands

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
docker compose logs -f runner notifier
docker compose exec api alembic revision --autogenerate -m "<message>"
cd frontend && npx playwright test
```

---

## Progress checklist (days 1–15)

- [ ] 1 — Compose skeleton, app factory, async DB + Alembic, Vite/React/TS via Caddy, logging,
      pytest harness, chaos skeleton; Playwright portfolio token extraction → `tokens.md`
- [ ] 2 — Full schema + migrations, constraints, partial indexes
- [ ] 3 — Auth: argon2, Postgres sessions, CSRF, signup/verify/login/logout/reset, auth rate limits
- [ ] 4 — API keys, `PLANS` (single `launch` plan) + `check_limit` + downgrade function, monitor
      CRUD API, save-time URL checks
- [ ] 5 — Design system + app shell: tokens, floating navbar, motion, transitions, auth + monitor UI
- [ ] 6 — Runner: claims, cadence, jitter, check-now, `runner_state` (stub probe)
- [ ] 7 — Probe: guarded backend, fresh connections, caps, timings, CheckResult, SSRF suite
- [ ] 8 — Incidents: counters, re-check, confirmation, canaries, ack + incidents UI
- [ ] 9 — Notifier: outbox, email, signed webhooks, retries, verification, routing, flapping, caps
- [ ] 10 — Heartbeats: ping/fail, `new`, sweep, ingest-outage suppression, slug rate limit + ECG UI
- [ ] 11 — Status pages: snapshots, cached public endpoint, private tokens, light bundle
- [ ] 12 — Rollups, charts, overview, command palette (SSE stretch)
- [ ] 13 — EWMA anomaly flag (advisory) + backtest notebook (cuttable)
- [ ] 14 — Hetzner deploy: domain + SPF/DKIM/DMARC, TLS, egress firewall, watchdog, canaries, backups
- [ ] 15 — Retention + usage rollups, settings/usage page with launch notice, `/pricing` page,
      docs, polish