# Cronos

Uptime monitoring for HTTP endpoints, heartbeat (dead man's switch) monitoring for cron jobs,
incidents, alerts (email + signed webhooks), and status pages. See `docs/cronos-srs.md` for the
full spec and `CLAUDE.md` for the day-by-day build order and non-negotiables.

## Setup

```bash
cp .env.example .env
docker compose up -d --build
```

This brings up Postgres, Redis, the api/runner/notifier processes, Caddy, the Vite dev server,
Mailpit and the chaos target. Only two ports are published on the host:

- `http://localhost:8080` — the app (SPA + `/api` + `/ping`, proxied through Caddy)
- `http://localhost:8026` — Mailpit's UI (dev email inbox)

Everything else (Postgres, Redis, the chaos target, the frontend's raw dev-server port) is
reachable only from other containers, never from the host.

## Design tokens (Day 1)

`frontend/design/tokens.md` and `extracted.json` are produced by scraping
`https://www.bonyaransom.me/` with Playwright:

```bash
docker compose --profile tools run --rm playwright
```

Review `frontend/design/tokens.md` before Day 5 builds the real design system on top of it.

## Common commands

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api pytest -q
docker compose logs -f runner notifier
docker compose exec api alembic revision --autogenerate -m "<message>"
cd frontend && npx playwright test   # once Day 5+ adds real UI screenshot tests
```

Frontend commands run **inside** the `frontend` container, not on the host — its
`node_modules` lives in a named Docker volume, not a bind mount:

```bash
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npx vitest run
```
