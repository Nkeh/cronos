# Day 1 summary

## What was built
Full Compose skeleton for Cronos: Caddy on one origin (`:8080`), FastAPI `api`, `runner` and
`notifier` tick loops, Postgres 16, Redis 7, Mailpit, and a chaos target — all behind a
two-network split (`data`, internal-only, vs `default`, egress-capable) with only Caddy and
Mailpit published to the host. A placeholder React/Vite/TS SPA proves the proxy and HMR work.
Design tokens extracted from bonyaransom.me via Playwright for approval before Day 5.

## Files changed (grouped by area)
- **Repo hygiene**: `.gitattributes`, `.gitignore`, `.editorconfig`, `.env.example`, `README.md`
- **Compose**: `compose.yaml` (prod-shaped base), `compose.override.yaml` (dev: mailpit, chaos,
  Vite dev server, ports, `--reload`), `caddy/Caddyfile`, `db/init/01-create-test-db.sh`
- **Backend** (`backend/`): app factory (`app/main.py`), `core/{config,logging,errors,db,redis,clock,tick_loop}.py`,
  `engine/runner.py`, `notifier/__main__.py`, Alembic (`alembic.ini`, `env.py`, baseline revision
  `0001`), two healthcheck scripts, `pyproject.toml`/`uv.lock`, Dockerfile, 5 test files (12 tests)
- **Chaos** (`chaos/`): tiny FastAPI app with `/_control` (up/down/slow), `pyproject.toml`/`uv.lock`,
  Dockerfile
- **Frontend** (`frontend/`): Vite+React+TS+Tailwind v4 scaffold, placeholder page + API-status
  pill (3 Vitest tests), ESLint/Prettier config, `package.json`/`package-lock.json`, Dockerfile,
  empty `components/ui`, `components/motion`, `features/`, `pages/public-status/` per the repo layout
- **Design tokens** (`frontend/design/`): `extract-tokens.mjs`, `tokens.md`, `extracted.json`,
  8 reference screenshots (736 KB — see Follow-up verification below)
- **Progress docs**: `docs/progress/day-01.md` (this file)

## Migrations
`0001_baseline` — empty up/down, just establishes the head revision. Real schema starts Day 2.

## Tests: 0 → 15
12 backend (pytest) + 3 frontend (Vitest). Two bugs surfaced and fixed while actually running the
suite (not just writing it):
- **404 error envelope wasn't firing** — the exception handler was registered on
  `fastapi.HTTPException`, but an unmatched route raises Starlette's base `HTTPException`
  directly; a subclass-registered handler never sees it. Fixed by registering on
  `starlette.exceptions.HTTPException`.
- **`RuntimeError: Event loop is closed`** in async fixture teardown — `pytest-asyncio` needs
  *both* `asyncio_default_fixture_loop_scope` and `asyncio_default_test_loop_scope` set to
  `"session"`; only the first was set, so fixtures and test items ran on different loops and
  asyncpg connections got torn down against a dead one.

## Live verification (commands + real output)
All 14 acceptance criteria run against the actual running stack (not just described):
- `docker compose up -d --build` → all 9 services healthy, `migrate` exited 0
- `docker compose port db 5432` / `redis 6379` → empty; `docker inspect` → no `PortBindings`;
  from **inside** `db`, DNS resolution timed out and a raw `/dev/tcp` connect returned
  `Network is unreachable` — `data` is genuinely internal, not just unpublished
- `/healthz` → 200; `/readyz` → `{"db":"ok","redis":"ok"}`; stopped Redis → still 200 with
  `"redis":"unavailable"`; restarted it → `"ok"` again
- Loaded `localhost:8080` in an actual Chrome tab (via claude-in-chrome) — "API up" pill
  rendered; edited the heading, screenshotted again ~2s later — text updated with the pill still
  showing "API up" (not reset to "Checking…"), confirming React Fast Refresh, not a full reload
- `/api/docs` → 200; Mailpit UI → 200
- Runner/notifier JSON tick lines every 30 ticks; `docker compose stop runner`/`notifier`
  individually → `*_shutdown_complete` logged, exit 0, in 1–2s
- `alembic current` → `0001 (head)`
- `pytest -q` → 12 passed; `vitest run` (in-container) → 3 passed
- Production guard: ran `create_app()` directly for all three refusal reasons, each raised
  `ConfigurationError` with the right message; separately confirmed the **real** prod command
  (`uvicorn` without `--reload`) exits immediately with code 1, no leftover container
- From inside `runner`: POSTed `/_control` to set chaos `/x` to `down 503`, then GET'd it → 503;
  `curl localhost:8000` from the host → exit 7 (connection refused)
- From inside `runner`: `urlopen('https://example.com')` → 200
- `grep -rlI $'\r' …` → no output
- `frontend/design/tokens.md`, `extracted.json`, 8 screenshots exist. Top findings: dark-only
  site (no theme toggle, light/dark emulation produced identical tokens), accent `#00C853`, fonts
  **Syne** (display) / **Outfit** (body/UI) / **DM Mono** (paragraph copy, unusually), dominant
  radius `2px`, one glow box-shadow recipe

## Deviations from SRS / CLAUDE.md
- **TypeScript 5.9.x, not 7.0** — confirmed with Oryn (tooling maturity over compiler speed on a
  foundation day).
- **Resolved all versions live via `uv add`/`npm install`, not hand-authored** — a first draft
  mixed incompatible pins (FastAPI 0.136 with pydantic/pytest-asyncio from a different era); the
  resolved table below is what's actually locked.
- **Backend venv at `/opt/venv`**, frontend `node_modules` in a named Docker volume shared with
  the `playwright` tools service — neither is a bind mount, per Oryn's amendment.
- **`db/init/`** is a new top-level directory not in CLAUDE.md's listed tree (holds the
  `cronos_test` creation script) — the listed tree wasn't exhaustive elsewhere either (e.g.
  `.gitattributes`, `docs/`).
- **`docs/progress/`** (this file) is likewise a new directory not in CLAUDE.md's listed tree,
  though CLAUDE.md does now require this file explicitly (§"End-of-day summary").
- **Day 1 frontend installs only what's used today** — `react-router`, `motion`,
  `@tanstack/react-query`, `recharts`, `lucide-react` are deferred to Days 5/8/9/12.
- **`frontend/design/extract-tokens.mjs`** is a plain Node script (full `playwright` package)
  rather than a Playwright *test* file — more natural for a scrape-and-dump task than
  shoehorning it into the test-runner's assertion model; still installed as a normal frontend
  devDependency.

## Resolved versions
`uv.lock` / `package-lock.json` are the source of truth; this is what they actually pinned (not
hand-guessed):

**Backend**

| Package | Version |
|---|---|
| fastapi | 0.142.2 |
| uvicorn[standard] | 0.54.0 |
| sqlalchemy[asyncio] | 2.1.3 |
| asyncpg | 0.31.0 |
| alembic | 1.20.0 |
| pydantic | 2.13.5 |
| pydantic-settings | 2.15.0 |
| httpx | 0.28.1 |
| structlog | 26.1.0 |
| sentry-sdk | 2.71.0 |
| redis[hiredis] | 8.1.0 |
| argon2-cffi | 25.1.0 |
| pytest (dev) | 9.1.1 |
| pytest-asyncio (dev) | 1.4.0 |
| uv (tool, pinned in Dockerfile) | 0.12.23 |

**Frontend**

| Package | Version |
|---|---|
| react / react-dom | 19.3.0 |
| typescript | 5.9.3 |
| vite | 8.3.3 |
| @vitejs/plugin-react | 6.1.2 |
| tailwindcss / @tailwindcss/vite | 4.3.3 |
| eslint | 10.12.0 |
| typescript-eslint | 8.71.1 |
| prettier | 3.9.9 |
| vitest | 5.0.3 |
| @playwright/test / playwright | 1.63.0 |

**Docker images (tag → resolved version → digest)**

| Image | Resolved | Digest |
|---|---|---|
| postgres:16 | 16.15 | `sha256:42df6755a4110ea9e324bfaefd02eb2f6afc0f0b9bc063c55c9f73dc29d25770` |
| redis:7-alpine | 7.4.11 | `sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499` |
| caddy:2-alpine | v2.11.7 | `sha256:1a81ac3d1a49b2b385a5bfafb8bd39fb40fa1d717461d825ee0d65df91a6e97b` |
| axllent/mailpit:latest | v1.31.4 | `sha256:b68349e3a014b90c5610bfb26b2ae36f3892d7b8cf25ee140c6c71c98d2fcf48` |
| python:3.12-slim-bookworm | 3.12.15 | `sha256:7753c33391fc9f01d1984375bf375eb6686d52ba10db6043a86634a5ccf90dcf` |
| node:lts-slim | v24.21.0 | `sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6` |
| mcr.microsoft.com/playwright:v1.63.0-noble | — | `sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27` |
| ghcr.io/astral-sh/uv (binary, copied into backend/chaos images) | 0.12.23 | `sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21` |

All pinned by digest in `compose.yaml` / `compose.override.yaml` / the Dockerfiles.

## Known issues / follow-ups
- `uvicorn --reload`'s change-reload supervisor **loops forever instead of exiting** when the app
  fails to import (e.g. the production guard raising) — only matters in dev (prod never uses
  `--reload`), but worth knowing if a container looks "stuck starting" during local debugging.
- Badge/pill elements weren't found on the four sampled portfolio pages — flagged in `tokens.md`
  rather than guessed.
- No `backdrop-filter` was observed anywhere on the site, so the floating navbar's glass blur
  (Day 5) has no extracted value to match — `blur(16px)` proposed as an unvalidated placeholder.
- `frontend/design/tokens.md` ends with four explicit open questions for Oryn
  (palette-match-vs-own-accent, light theme yes/no, missing badge/pill reference, placeholder
  blur value) — worth a look before Day 5.
- ~~A `cronos_frontend_node_modules` Docker volume created by hand during dependency resolution
  predated Compose's own bookkeeping, producing a harmless "volume already exists" warning~~ —
  **resolved**, see Follow-up verification below.
- **`tokens.md`'s Proposed section now conflicts with the updated CLAUDE.md UI rules** (2026-10-07
  revision): it treats a light theme as optional/deferred and reuses green as the general
  interactive accent, while CLAUDE.md now mandates two first-class themes (dark + light, OS-default
  with a persisted toggle) and green reserved **only** for status/brand with a separate cool
  interactive accent for buttons/links/focus/nav. Per Oryn's explicit instruction this round,
  `tokens.md`'s content was left untouched — this needs a real revision pass before Day 5, not a
  silent reconciliation.

## Follow-up verification (2026-10-06, after Oryn's first review)

**Orphan volume fix.** `docker compose down` (containers + networks only, `pg_data` kept) →
`docker volume rm cronos_frontend_node_modules` → `docker compose up -d`. Result: no "volume
already exists but was not created by Docker Compose" warning on either the initial `up -d` or a
second, idempotent `up -d` run immediately after. `docker volume inspect` now shows proper
`com.docker.compose.{project,version,volume,config-hash}` labels — Compose fully owns the volume.
HMR re-verified in a real browser tab after the rebuild: edited `App.tsx`'s heading to "Cronos.
(volume HMR recheck)", screenshot ~2s later showed the updated text with the API-status pill still
reading "API up" (no full reload), then reverted. All 9 services came back healthy.

**`.env` / git hygiene.** `git check-ignore -v .env` → matched by `.gitignore:18:.env`.
`git status --porcelain -- .env` → no output (not tracked, not listed as untracked — correctly
invisible to git). Confirmed no `.env` line appears anywhere in `git status` output.

**`frontend/design/reference/` size (original).** 16 PNGs, 11 MB (11,330,367 bytes) total.
Superseded below after the 2026-10-07 shrink.

## Follow-up verification (2026-10-07, after Oryn's second review)

**Screenshots shrunk.** `extract-tokens.mjs` captured both `light` and `dark`
`prefers-color-scheme` emulations, even though the first run had already proven they produce
byte-identical `:root` tokens (the site is dark-only, no theme toggle). Changed `THEMES` to
`['dark']` only, and switched the screenshot call from PNG to
`{ type: 'jpeg', quality: 75 }` (`.jpg` extension). Re-ran via
`docker compose --profile tools run --rm playwright` — **0 extraction errors**. Spot-checked the
new `extracted.json` against what `tokens.md` already documents (fonts, `:root` vars, top colours,
border-radius, box-shadow, `h1`/`p` computed styles): all identical except one frequency count off
by 1 (`rgba(0,0,0,0)`: 559 → 558, page-load noise, not a real change) — so per Oryn's instruction,
`tokens.md`'s prose was left as-is. Deleted the 16 old PNGs. Result: **8 screenshots, 736 KB
(731,438 bytes) total** — down from 11 MB, a 15.4× reduction.

**Provenance note removed** from the top of this file — CLAUDE.md's 2026-10-07 revision now
explicitly requires `docs/progress/day-NN.md`, so the earlier discrepancy no longer applies.

**New discrepancy found and flagged** (not acted on, per scope): the same CLAUDE.md revision
rewrote the UI non-negotiables (two first-class themes, green reserved for status/brand only,
separate interactive accent) in a way that now conflicts with `tokens.md`'s Proposed section
written on Day 1. See Known issues above.

## Commit block

```bash
git add -A
git commit -m "day 1: Compose skeleton, app factory, async DB + Alembic, Vite/React/TS via Caddy, logging, pytest harness, chaos skeleton; Playwright extraction of portfolio tokens" -m "- Two-network Compose topology: data (internal-only) vs default (egress); only caddy:8080 and mailpit:8026 published
- FastAPI api with /healthz, /readyz, production guard (refuses ENV=production with SSRF_ALLOW_HOSTS set / example SECRET_KEY / DEBUG on)
- runner (2s) and notifier (1s) tick loops sharing a tick-loop helper; graceful SIGTERM/SIGINT shutdown under 5s
- Async Alembic env with a baseline revision; backend tests run real migrations against cronos_test, not metadata.create_all
- Chaos target with /_control (up/down/slow), reachable only from other containers
- Vite+React+TS+Tailwind v4 placeholder SPA with an API-status pill; HMR verified live through Caddy, including after rebuilding the node_modules volume under Compose's own management
- 15 tests (12 backend, 3 frontend), all passing
- Design tokens extracted from bonyaransom.me into frontend/design/ for approval before Day 5; screenshots are single-theme JPEG (8 files, 736 KB) after confirming light/dark emulation is identical on this dark-only site
- docs/progress/day-01.md added with the full summary, resolved-versions table, and both follow-up review rounds
- Flagged for Day 5: tokens.md's Proposed section predates CLAUDE.md's 2026-10-07 UI-rules rewrite (two themes, green reserved for status only) and needs a revision pass"
```
