## Day 5a summary

### What was built

**Token architecture** — `frontend/src/styles/index.css`: Tailwind v4 `@theme inline` mapping
semantic CSS custom properties (bg/surface/surface-raised/border/text/accent/accent-solid/
focus-ring/status-{up,down,degraded,paused}-{dot,text}/glass-bg/glass-border/glow) to utility
classes, with dark values under `:root[data-theme="dark"]` and a `prefers-color-scheme: dark`
media query guarded by `:not([data-theme="light"])` for the default "system" case. Approved design
decisions from this session's design-review questions are baked in: Electric Blue accent
(`#3B82F6` dark / `#2563EB` light, separate from brand green), cool off-white light base, medium
glow intensity (the extracted recipe reused verbatim), 16px glass blur, outlined-with-dot status
pills, faint grid + radial-glow ambient background. `frontend/design/tokens.md`'s "Proposed"
section is now "Approved" with final values. No-flash inline script added to `index.html`
(`data-theme` set only for an explicit light/dark choice; "system" relies on the media query
alone, never gets the attribute).

**Checkpoint A** — a dev-only `/dev/design` route (tree-shaken from production via
`import.meta.env.DEV`) was built, screenshotted in both themes at 1440px, and **approved by Oryn**
before any further component was built.

**Motion system** — `components/motion/`: shared duration/ease/spring tokens, `PageTransition`
(fade + 8px rise, no blur), `Stagger`/`StaggerItem`, `NumberTicker` (wired in, unused until later
days' numeric data), a CSS shimmer `Skeleton`. App root wraps in `MotionConfig reducedMotion="user"`
plus a global `@media (prefers-reduced-motion: reduce)` CSS fallback.

**App shell + floating navbar** — `AuthLayout`/`AppLayout`, route map per the brief
(`/login /signup /verify /forgot /reset` unauthenticated; `/ /monitors /monitors/new
/monitors/:id/edit /heartbeats /incidents /status-pages` behind the auth guard, not-yet-built
sections rendering a designed `PlaceholderPage`). `Navbar` tree: rounded-full glass capsule,
Motion shared-`layoutId` active pill, `IncidentsBadge` (wired to 0 until Day 8),
`AccountMenu` (Radix DropdownMenu: email, theme switch, log out), `SearchDialog` (Radix Dialog
placeholder, ⌘K-triggered), scroll-direction compaction, full keyboard reach, Radix Tooltip on
each item. `UnverifiedBanner` with a working "Resend email" action.

**Typed API client + auth screens** — `lib/api/client.ts` extended with `apiRequest<T>()`: reads/
sends the `cronos_csrf` cookie/header, retries once on `403 csrf_failed` after refreshing the
cookie, maps `{"error":{code,message,field}}` onto a typed `ApiError`, parses `Retry-After` on
429. Five auth screens (`features/auth/`) wired to the Day-3 API: Login (`invalid_credentials`
form error, `?next` redirect), Signup (password hint, `weak_password` field error, "check your
email" state), Verify (button-triggered POST only — never on page load), Forgot (constant
confirmation copy), Reset (token + new password → redirect to login). Logout clears the TanStack
Query cache.

### Files changed (grouped by area)

- **Tokens/theme**: `frontend/src/styles/index.css`, `frontend/index.html`,
  `frontend/design/tokens.md`, `frontend/src/features/theme/` (`ThemeProvider.tsx`,
  `theme-storage.ts` + tests)
- **Motion**: `frontend/src/components/motion/` (`tokens.ts`, `PageTransition.tsx`, `Stagger.tsx`,
  `NumberTicker.tsx`)
- **UI primitives**: `frontend/src/components/ui/` (`Button.tsx`, `Input.tsx`, `GlassPanel.tsx`,
  `StatusPill.tsx`, `Skeleton.tsx`, `FormField.tsx`), `frontend/src/lib/cn.ts`
- **App shell**: `frontend/src/app/router.tsx`, `frontend/src/app/layouts/`,
  `frontend/src/app/shell/` (`PageHeader.tsx`, `PlaceholderPage.tsx`, `UnverifiedBanner.tsx`,
  `Navbar/`)
- **API client**: `frontend/src/lib/api/` (`client.ts` extended, `errors.ts`, `types.ts`,
  `auth.ts`, `usage.ts`, `error-copy.ts`), `frontend/src/lib/queryClient.ts`
- **Auth screens**: `frontend/src/features/auth/` (`AuthCard.tsx`, `LoginPage.tsx`,
  `SignupPage.tsx`, `VerifyPage.tsx`, `ForgotPage.tsx`, `ResetPage.tsx`, `hooks.ts`)
- **Toasts**: `frontend/src/features/toast/ToastProvider.tsx`
- **Dev-only design preview**: `frontend/src/pages/dev-design/DesignPreviewPage.tsx`
- **Overview (stub, full version is Day 5b)**: `frontend/src/pages/overview/OverviewPage.tsx`
- **Root wiring**: `frontend/src/app/App.tsx`, `frontend/src/main.tsx` (unchanged, already correct)
- **Tests**: `frontend/src/**/*.test.{ts,tsx}` (6 files), `frontend/playwright.config.ts`,
  `frontend/tests/e2e/` (`auth.spec.ts`, `navbar.spec.ts`, `axe.spec.ts`, `screenshots.spec.ts`,
  `global-setup.ts`, `build-contact-sheets.mjs`, `helpers/`)
- **Infra**: `compose.override.yaml` (new `pw-tests` service), `.gitignore`,
  `frontend/tsconfig.node.json`, `frontend/vitest.config.ts`, `frontend/vitest.setup.ts`,
  `frontend/eslint.config.js`, `frontend/src/vite-env.d.ts`

### Migrations

None — Part A is frontend-only.

### Dependencies added (exact versions, resolved via `npm view`)

```
react-router 8.4.0, @tanstack/react-query 5.104.2, motion 14.2.0, lucide-react 1.56.0,
@radix-ui/react-dialog 1.3.1, @radix-ui/react-dropdown-menu 2.2.1, @radix-ui/react-tooltip 1.4.1,
@fontsource-variable/syne 5.3.0, @fontsource-variable/outfit 5.3.0, @fontsource/dm-mono 5.3.0,
clsx 2.1.1, tailwind-merge 3.7.0, class-variance-authority 0.7.1,
@axe-core/playwright 4.13.0 (dev), @types/node 24.19.2 (dev), @testing-library/react 16.3.3 (dev)
```
All three font packages are Google Fonts under SIL OFL 1.1 (confirmed via each package's `LICENSE`
file) — free to self-host and use commercially. `@types/node` and `@testing-library/react` weren't
in the original dependency list from the brief; both are dev-only infra additions, not product
dependencies — see Deviations below.

### Tests: 3 → 26 (Vitest) · 0 → 23 (Playwright, new) · 208 → 208 (pytest, untouched)

Vitest (6 files, all passing): theme storage + live OS-follow via `ThemeProvider`, `apiRequest`'s
CSRF retry-once/error-mapping/Retry-After parsing, `NavItem`'s `aria-current` assignment, and
`SignupPage`'s password-policy UI.

Playwright (23 tests, `docker compose --profile tools run --rm pw-tests`, serial/`workers: 1`):
full signup→Mailpit→verify→login→navbar→logout flow, unverified-banner flow, invalid-credentials
error, forgot→reset→login flow, axe on every auth page + the authenticated overview page in both
themes (**zero serious/critical violations**), navbar geometry/`aria-current`/keyboard-reach at
375/768/1440px, active-pill behavior under reduced motion, and the full screenshot-matrix capture.
All 23 pass.

pytest unaffected (208 passed, 1 deselected) — Part A touches no backend code; run as a sanity
check per CLAUDE.md's "verify against the running stack" rule.

### Live verification (commands + real output)

```bash
docker compose up -d --build                 # full stack healthy
docker compose exec frontend npx vitest run   # 6 files / 26 tests passed
docker compose exec frontend npm run lint     # 0 errors
npm run build                                  # tsc -b && vite build — succeeds
docker compose exec api pytest -q             # 208 passed, 1 deselected
docker compose --profile tools run --rm pw-tests          # 22/23, then 23/23 after fixes below
docker compose --profile tools run --rm pw-tests node tests/e2e/build-contact-sheets.mjs
```

Manual click-through in Chrome against the live stack (not just automated): signup → Mailpit
(`GET /api/v1/search?query=to:...`) → verify-button click (confirmed it does **not** POST on page
load) → login → navbar nav with the active pill sliding between Overview/Monitors → Account menu
theme toggle (System/Light/Dark, instant across the whole shell, **persists across a hard reload
with no flash**) → logout (redirects to `/login`, clears the query cache) → direct navigation to a
guarded route while logged out redirects to `/login?next=...` → wrong-password login shows "That
email or password is incorrect." inline.

**Production build** (`npm run build`): `/dev/design` does **not** appear in `dist/` — confirmed
dead-code-eliminated. Auth routes are lazy-split (`LoginPage`/`SignupPage`/`VerifyPage`/
`ForgotPage`/`ResetPage`/`AuthCard`/`Input` each 0.4–1.6 kB raw). Main chunk: 577 kB raw / 185 kB
gzip — larger than ideal since `AppLayout`/`Navbar` (Radix + Motion + TanStack Query + React
Router) load eagerly; flagged below as a Day 5b follow-up once monitor routes exist to split
against.

**Screenshot matrix**: 84 screenshots in `frontend/tests/screenshots/` (gitignored) — 7 pages
(login, signup, verify, forgot, reset, dev-design, overview) × 3 widths × 2 themes × 2
reduced-motion states. Contact sheets (one PNG grid per page) at:

```
frontend/tests/screenshots/contact-sheets/login.png
frontend/tests/screenshots/contact-sheets/signup.png
frontend/tests/screenshots/contact-sheets/verify.png
frontend/tests/screenshots/contact-sheets/forgot.png
frontend/tests/screenshots/contact-sheets/reset.png
frontend/tests/screenshots/contact-sheets/dev-design.png
frontend/tests/screenshots/contact-sheets/overview.png
```

### Deviations from SRS / CLAUDE.md

- **`--accent-solid` added alongside `--accent`**: the bright accent (`#3B82F6` dark) only hits
  ~3.7:1 contrast with white text (fails AA normal text), so filled-button backgrounds use a
  separate, slightly darker `--accent-solid: #2563EB` (both themes) instead. Flagged at Checkpoint
  A, not decided silently.
- **Light-theme `down`/`degraded`/`paused` text colors are computed estimates, not independently
  verified**: only `up`'s light-safe value (`#00A847`) came from the earlier token-extraction
  session; the other three were derived by the same darkening approach for consistency. Worth a
  contrast-checker pass before they're load-bearing beyond `/dev/design`.
- **`@types/node` and the `tsconfig.node.json` `outDir`/`.gitignore` `*.tsbuildinfo` fix**: Day 1's
  `vite.config.ts` used `process.env` with no `@types/node` installed, which made `tsc -b` (and
  therefore `npm run build`) fail outright, and — once fixed — `tsc -b`'s composite-project emit
  was writing `vite.config.js`/`.d.ts` straight into `frontend/` with no `outDir`. Fixed both
  (pinned `@types/node@24.19.2` to match the Dockerfile's `node:lts-slim` line) since they blocked
  running the build at all, not a Day 5 feature.
- **`frontend/src/vite-env.d.ts` added**: missing from Day 1's scaffold (the standard Vite
  template file); `import.meta.env.DEV` has no type without it.
- **`@testing-library/react@16.3.3` added** (dev-only): needed to fulfill the Part A test plan's
  "navbar active-state logic" and "signup/login form validation" Vitest items, which require
  rendering components, not just pure-function tests. Not in the brief's dependency list; added as
  test infra rather than re-asking mid-build, called out here instead.
- **`eslint.config.js` extended with a `.mjs` globals block**: needed for the new
  `build-contact-sheets.mjs` script (which mixes Node orchestration with `page.evaluate()`
  browser-context closures); this also incidentally fixed 16 pre-existing lint errors in Day 1's
  `extract-tokens.mjs` that were never covered by any globals config.
- **`README.md`**: found a stray corrupted backtick (`` `http://localhos`t:8080` ``) unrelated to
  this work — fixed in passing rather than leaving broken markdown in the repo.
- **Playwright runs serially (`workers: 1`) with a shared test user via `globalSetup`**: signup is
  rate-limited to 5/hour per IP (`app/core/config.py`), and every request from the `pw-tests`
  container shares one apparent IP via `network_mode: service:caddy`. Running the originally
  fully-parallel suite burned through that budget in minutes and cascaded into failures. Most
  specs now reuse one shared signed-up/verified account's `storageState`; only the four
  `auth.spec.ts` tests that exercise the signup/verify/forgot/reset flows themselves create fresh
  accounts (4 signups/run, under the 5/hour cap).

### Known issues / follow-ups

- **Day 5b** (separate session, per the SPLIT RULE): monitor UI (list/create/edit/pause/resume/
  delete, usage bar, limit states), the dev-data CLI (`create-user`/`seed-demo`), and the
  remaining Part-8 test items (monitor E2E flows, a blocked-URL field error, the 15-monitor limit
  state, the full screenshot matrix extended to monitor pages).
- Main JS chunk is 577 kB raw / 185 kB gzip — worth revisiting chunk-splitting strategy once the
  monitor feature (and its own Radix/Motion usage) exists to split against in Day 5b.
- Re-running the Playwright suite repeatedly within the same hour during local iteration can hit
  the signup rate limit from prior runs; `docker compose exec redis redis-cli FLUSHALL` clears it
  (Redis is explicitly non-critical cache/rate-limit state per CLAUDE.md, safe to flush in dev).
- `IncidentsBadge` is wired to a hardcoded `0` until Day 8 provides real incident counts.
- Overview (`/`) is currently just a header stub; real monitor-count tallying is Day 5b.

### Commit block

```bash
git add -A
git commit -m "day 5a: design system, app shell, floating navbar, auth screens" -m "$(cat <<'EOF'
- Token architecture (Tailwind v4 @theme, dark/light, no-flash inline script), Checkpoint A
  approved by Oryn before building further components
- Motion primitives (PageTransition, Stagger, NumberTicker, shimmer Skeleton) on shared tokens
- App shell: AuthLayout/AppLayout, route map with designed placeholders, floating glass navbar
  (shared-layoutId active pill, incidents badge, account menu, search dialog, scroll compaction)
- Typed API client (CSRF retry-once, error mapping, Retry-After) + five auth screens wired to
  the Day 3 API (login/signup/verify/forgot/reset), unverified-email banner
- Playwright suite (auth/navbar/axe/screenshot-matrix, 23 tests) via a new pw-tests Compose
  service; Vitest 3 -> 26; pytest unchanged at 208
- Fixed three pre-existing Day 1 infra gaps hit while verifying the build (@types/node,
  tsc -b outDir, *.tsbuildinfo gitignore) and a stray README.md typo
EOF
)"
```
