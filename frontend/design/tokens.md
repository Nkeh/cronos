# Design tokens — extracted from bonyaransom.me

Extracted 2026-10-06 by `frontend/design/extract-tokens.mjs` (Playwright, run via
`docker compose --profile tools run --rm playwright`). Source: https://www.bonyaransom.me/,
pages `/`, `/about`, `/projects`, `/contact`, at 375px and 1440px, with `prefers-color-scheme`
emulated both light and dark. Raw data in `extracted.json`; full-page screenshots in
`reference/` (16 total: 4 pages × 2 widths × 2 emulated themes).

No source code, images or font files were copied — only computed styles, CSS custom property
values, and font family *names* read from the rendered page.

---

## Part 1 — Observed

**The site is dark-only.** No theme toggle was found (heuristic search for
`[aria-label*="theme"]` / `.theme-toggle`-style elements), and the light- vs
dark-`prefers-color-scheme` emulation produced byte-identical `:root` custom
property values. There is no light palette to extract — only dark.

### `:root` custom properties (all 20, identical in both emulated themes)

```css
--bg-primary:     #080A08
--bg-secondary:   #0D110D
--bg-surface:     #111611
--bg-elevated:    #161D16
--bg-card:        #1A221A

--border-subtle:  rgba(0,200,83,0.08)
--border-default: rgba(0,200,83,0.15)
--border-strong:  rgba(0,200,83,0.35)

--green:          #00C853
--green-dim:      rgba(0,200,83,0.10)
--green-glow:     rgba(0,200,83,0.25)
--green-bright:   #00E676

--text-primary:   #F0F5F0
--text-secondary: #8A9E8A
--text-muted:     #4A5E4A
--text-accent:    #00C853

--font-display:   "Syne", sans-serif
--font-mono:      "DM Mono", monospace
--font-body:      "Outfit", sans-serif

--navbar-h:       72px
```

### Type scale (computed, home page / 1440px)

| Element | Font | Size | Weight | Line height | Letter spacing | Colour |
|---|---|---|---|---|---|---|
| `body` | Outfit | 16px | 400 | 27.2px | normal | `#F0F5F0` on `#08 0A 08` |
| `h1` | Syne | 72px | 700 | 72px | -1.44px | `#F0F5F0` |
| `h2` | Syne | 48px | 700 | 48px | -0.96px | `#F0F5F0` |
| `h3` | Syne | 16px | 700 | 20px | -0.32px | `#F0F5F0` |
| `p` | **DM Mono** | 16px | 400 | 27.2px | -0.4px | `#8A9E8A` (text-secondary) |
| `a` | Outfit | 16px | 400 | 27.2px | normal | `#F0F5F0` |
| `button` | Outfit | 16px | 400 | 27.2px | normal | `#8A9E8A` |
| `nav`, `header` | Outfit | 16px | 400 | 27.2px | normal | `#F0F5F0` |
| card-like (`[class*="card"]`) | Outfit | 16px | 400 | 27.2px | normal | bg `#1A221A` (bg-card), radius 2px |

Body copy (`<p>`) runs in the **monospace** face, not the body sans — a deliberate "terminal
readout" feel worth carrying into Cronos's latency numbers / status text.

Font families found via `document.fonts`: **Syne** (display/headings), **Outfit** (body/UI),
**DM Mono** (paragraph copy). Licensing: all three are open-source Google Fonts families
(SIL Open Font License) — safe to self-host or pull from Google Fonts; not verified against the
portfolio's own hosting method since that wasn't inspected.

Badge/pill elements (CLAUDE.md mentions "Open to Work"-style pills) were **not found** by the
`[class*="badge"]` / `[class*="pill"]` heuristic on these four pages — either the class naming
differs or the portfolio's pill lives on a page not sampled today. Flagging as an observed gap
rather than guessing its styling.

### Frequencies (top values across all elements, home page / 1440px)

- **Top colours:** `rgb(229,231,235)` ×572 (likely an unstyled default, not a design colour),
  `rgba(0,0,0,0)` ×559 (transparent), `rgb(240,245,240)` ×300 (`--text-primary`),
  `rgb(0,200,83)` ×175 (`--green`), `rgb(74,94,74)` ×92 (`--text-muted`),
  `rgb(138,158,138)` ×55 (`--text-secondary`).
- **Border radius:** `2px` ×61 (dominant), `9999px` ×42 (pills/orbs), `4px` ×15, `3px` ×4.
- **Box shadow:** one distinct glow recipe, used once:
  `rgba(0,200,83,0.25) 0 0 30px 0, rgba(0,200,83,0.08) 0 0 60px 0` — a soft green glow, matches
  `--green-glow`.
- **Backdrop filter:** none detected on the sampled pages (no glass/blur surfaces found today —
  worth re-checking manually before Day 5 builds the floating navbar's glass capsule).
- **Transition duration:** `0.2s` ×26, `0.15s` ×20, a `0.3s, 0.3s, 0.3s` multi-property group ×15,
  `0.25s` ×2.
- **Transition timing function:** `ease` dominant (×603), `cubic-bezier(0.4, 0, 0.2, 1)` ×35
  (standard Material-style ease), a matching triple-group ×15.
- **Keyframe names** (same-origin stylesheets): `pulse`, `spin`, plus seven hashed/generated
  names (`go2264125279` etc. — almost certainly a CSS-in-JS or build-tool output, not meaningful
  as names).

---

## Part 2 — Approved Cronos tokens (Day 5, Oryn's sign-off via AskUserQuestion)

**Accent (SRS §17 question, resolved)**: Cronos does **not** reuse the portfolio's green as its
interactive accent — CLAUDE.md reserves green exclusively for status/brand, and requires "a
separate cool interactive accent" for buttons/links/focus rings/the active nav pill. Chosen:
**Electric Blue** — dark `#3B82F6` (~11:1 on `#080A08`), light `#2563EB` (~4.8:1 on white).
Filled-button surfaces use a darker `--accent-solid: #2563EB` in both themes (white text on the
bare dark-theme accent would only be ~3.7:1, failing AA; `#2563EB` with white text clears ~4.8:1
in both themes) — a judgment call made during implementation, not re-asked.

**Light theme (resolved)**: CLAUDE.md mandates two first-class themes, superseding this file's
earlier "optional/deferred" framing — light is built out fully in Day 5, base **cool off-white**
(`#F7F9F7` primary / `#FFFFFF` surface), as sketched below.

**Badge/pill styling (resolved)**: none was found in the scrape (see Part 1), so Day 5 uses
**outlined-with-dot** — transparent background, 1px border in the status colour, coloured dot +
text — chosen for its minimal, hairline-consistent look and clean WCAG story in both themes.

**Glass blur (resolved)**: `16px`, with an opaque `--glass-bg` fallback where `backdrop-filter`
isn't supported.

### Dark theme (adopted near-verbatim from Observed; accent is new, not reused green)

```css
--bg:             #080A08;
--surface:        #111611;
--surface-raised: #1A221A;

--border:         rgba(0, 200, 83, 0.15);
--border-subtle:  rgba(0, 200, 83, 0.08);
--border-strong:  rgba(0, 200, 83, 0.35);

--text:           #F0F5F0;
--text-muted:     #8A9E8A;

--accent:         #3B82F6;  /* Electric Blue — new, separate from brand green */
--accent-solid:   #2563EB;  /* filled-button background, both themes (AA with white text) */
--accent-fg:      #FFFFFF;
--focus-ring:     #3B82F6;

--status-up-dot:        #00C853;  --status-up-text:        #00C853;
--status-down-dot:      #FF6E6E;  --status-down-text:      #FF6E6E;
--status-degraded-dot:  #FFC24B;  --status-degraded-text:  #FFC24B;
--status-paused-dot:    #9CA3AF;  --status-paused-text:    #9CA3AF;

--glow:        0 0 30px 0 rgba(0, 200, 83, 0.25), 0 0 60px 0 rgba(0, 200, 83, 0.08);
--glass-bg:    rgba(17, 22, 17, 0.6);
--glass-border: rgba(0, 200, 83, 0.15);
--glass-blur:  16px;
```

### Light theme (cool off-white, built out fully — no longer optional)

```css
--bg:             #F7F9F7;
--surface:        #FFFFFF;
--surface-raised: #EFF3EF;

--border:         rgba(0, 150, 64, 0.22);
--border-subtle:  rgba(0, 150, 64, 0.12);
--border-strong:  rgba(0, 150, 64, 0.40);

--text:           #0B140B;
--text-muted:     #3F4F3F;

--accent:         #2563EB;  /* darkened for ~4.8:1 on white */
--accent-solid:   #2563EB;
--accent-fg:      #FFFFFF;
--focus-ring:     #2563EB;

/* Dots stay vivid in both themes (small non-text graphics, 3:1 threshold); text variants darken
   for 4.5:1 on a near-white surface — the same pattern CLAUDE.md specifies for green, extended
   to all four statuses for consistency. */
--status-up-dot:        #00C853;  --status-up-text:        #00A847;  /* ~? : 1, verify at Checkpoint A */
--status-down-dot:      #FF6E6E;  --status-down-text:      #C9372C;
--status-degraded-dot:  #FFC24B;  --status-degraded-text:  #946800;
--status-paused-dot:    #9CA3AF;  --status-paused-text:    #5B6472;

--glow:        0 0 0 3px rgba(0, 168, 71, 0.16), 0 2px 10px 0 rgba(11, 20, 11, 0.08); /* tinted ring + soft shadow, not a glow */
--glass-bg:    rgba(255, 255, 255, 0.65);
--glass-border: rgba(0, 150, 64, 0.22);
--glass-blur:  16px;
```

### Type scale (carried from Observed; `eyebrow` added as a new, distinct small-caps-style token)

```css
--font-display: "Syne Variable", sans-serif;
--font-mono:    "DM Mono", monospace;
--font-body:    "Outfit Variable", sans-serif;

--text-display-1: 72px/72px;   letter-spacing: -1.44px; weight: 700; /* h1 */
--text-display-2: 48px/48px;   letter-spacing: -0.96px; weight: 700; /* h2 */
--text-heading-3: 16px/20px;   letter-spacing: -0.32px; weight: 700; /* h3 */
--text-eyebrow:   13px/16px;   letter-spacing: 0.08em;  weight: 600; /* new — portfolio's "small line above headings" motif, no verbatim source to carry over, paired with an uppercase utility class */
--text-body:      16px/27.2px; letter-spacing: normal;  weight: 400;
--text-mono:      16px/27.2px; letter-spacing: -0.4px;  weight: 400; /* latency/uptime numbers, tabular-nums */
```

### Radii & glass/glow

```css
--radius-sm:   2px;    /* surfaces/cards/inputs — overrides Tailwind's default `rounded-sm` */
--radius-full: 9999px; /* navbar/pills/orbs — Tailwind's built-in `rounded-full`, unchanged */
```

Glass blur resolved at **16px** (no observed source — `backdrop-filter` wasn't found anywhere in
the scrape — this was Oryn's choice from 12/16/24px options, with an opaque `--glass-bg` fallback
for unsupported browsers).

### Motion tokens

```css
--duration-fast: 150ms;
--duration-base: 250ms;
--duration-slow: 400ms;

--ease:   cubic-bezier(0.4, 0, 0.2, 1); /* matches the observed non-default easing */
--spring: { stiffness: 300, damping: 30 }; /* Motion spring config, visually tuned at Checkpoint A */
```

### Status colours — WCAG contrast

| Status | Dark (dot = text) | vs `#080A08` | vs `#1A221A` | Light text | vs `#FFFFFF` |
|---|---|---|---|---|---|
| up | `#00C853` | 8.88:1 | 7.29:1 | `#00A847` | ≥4.5:1 (reused from earlier light-theme sketch) |
| down | `#FF6E6E` | 7.29:1 | 5.99:1 | `#C9372C` | ~5:1 (estimate, confirm visually at Checkpoint A) |
| degraded | `#FFC24B` | 12.36:1 | 10.15:1 | `#946800` | ~5.5:1 (estimate) |
| paused | `#9CA3AF` | 7.82:1 | 6.42:1 | `#5B6472` | ~6:1 (estimate) |

Dark-theme numbers are measured (Part 1 extraction + direct computation). The three new
light-theme text colours (down/degraded/paused) are reasoned estimates following the same
darkening approach already validated for `up` — Checkpoint A's screenshot review is the point
where these get a final visual/contrast-tool check before they're used anywhere beyond
`/dev/design`.

### Resolved (previously "Still open for Oryn")

All four items from the original "Still open" list were resolved via this session's
AskUserQuestion rounds: accent is a new Electric Blue (not reused green), light theme is fully
built (not optional), pill styling is outlined-with-dot (no portfolio reference existed), and
glass blur is 16px (no portfolio reference existed). See the top of this section for the
rationale on each.
