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

## Part 2 — Proposed Cronos tokens (awaiting Oryn's approval)

**Open question carried over from SRS §17**: should Cronos match this palette exactly, or take
its own accent within the same system? The proposal below **reuses the observed system directly**
(same green, same near-black scale) rather than inventing a new accent, since Cronos is explicitly
meant to read as "part of the same body of work." Swap `--cronos-accent` for a different hue below
if Oryn prefers Cronos to stand apart.

The source site is dark-only; Cronos's own non-negotiable is just "dark-first," not
light-and-dark, so **a light theme is proposed as optional/deferred** — a minimal skeleton is
included below so Day 5 isn't starting from nothing if Oryn wants one, but building it out is not
assumed.

### Dark theme (primary — adopted near-verbatim from Observed)

```css
--cronos-bg-primary:    #080A08;
--cronos-bg-surface:    #111611;
--cronos-bg-elevated:   #161D16;
--cronos-bg-card:       #1A221A;

--cronos-border-subtle:  rgba(0, 200, 83, 0.08);
--cronos-border-default: rgba(0, 200, 83, 0.15);
--cronos-border-strong:  rgba(0, 200, 83, 0.35);

--cronos-accent:        #00C853;  /* reused from the portfolio's --green */
--cronos-accent-bright: #00E676;
--cronos-accent-glow:   rgba(0, 200, 83, 0.25);

--cronos-text-primary:   #F0F5F0;
--cronos-text-secondary: #8A9E8A;
--cronos-text-muted:     #4A5E4A;
```

### Light theme (optional — skeleton only, not derived from any observed data)

```css
--cronos-bg-primary:    #F7F9F7;
--cronos-bg-surface:    #FFFFFF;
--cronos-bg-elevated:   #FFFFFF;
--cronos-bg-card:       #EFF3EF;

--cronos-border-subtle:  rgba(0, 150, 64, 0.12);
--cronos-border-default: rgba(0, 150, 64, 0.22);
--cronos-border-strong:  rgba(0, 150, 64, 0.40);

--cronos-accent:        #00A847;  /* darkened for 4.5:1+ on a light surface */
--cronos-accent-bright: #00C853;
--cronos-accent-glow:   rgba(0, 150, 64, 0.18);

--cronos-text-primary:   #0B140B;
--cronos-text-secondary: #3F4F3F;
--cronos-text-muted:     #6B7C6B;
```

### Type scale (carried from Observed, renamed)

```css
--cronos-font-display: "Syne", sans-serif;
--cronos-font-mono:    "DM Mono", monospace;
--cronos-font-body:    "Outfit", sans-serif;

--cronos-text-display-1: 72px/72px;   letter-spacing: -1.44px; weight: 700; /* h1 */
--cronos-text-display-2: 48px/48px;   letter-spacing: -0.96px; weight: 700; /* h2 */
--cronos-text-eyebrow:   16px/20px;   letter-spacing: -0.32px; weight: 700; /* h3 / eyebrow */
--cronos-text-body:      16px/27.2px; letter-spacing: normal;  weight: 400;
--cronos-text-mono:      16px/27.2px; letter-spacing: -0.4px;  weight: 400; /* latency/uptime numbers */
```

### Radii & glass/glow (carried from Observed)

```css
--cronos-radius-sm:   2px;   /* dominant radius observed */
--cronos-radius-md:   4px;
--cronos-radius-pill: 9999px;

--cronos-glow-sm: 0 0 30px 0 rgba(0, 200, 83, 0.25), 0 0 60px 0 rgba(0, 200, 83, 0.08);
```

No `backdrop-filter` was observed on the sampled pages. The floating navbar's glass capsule
(CLAUDE.md, signature component) will need its own blur value — propose `backdrop-filter:
blur(16px)` as a starting point for Day 5, since nothing was observed to carry over.

### Motion tokens (SRS §9 durations, informed by Observed timing functions)

```css
--cronos-duration-fast:   150ms;
--cronos-duration-base:   250ms;
--cronos-duration-slow:   400ms;

--cronos-ease:   cubic-bezier(0.4, 0, 0.2, 1); /* matches the observed non-default easing */
--cronos-spring: { stiffness: 300, damping: 30 }; /* Motion spring config, tune at Day 5 */
```

### Status colours (dark theme) — WCAG contrast against `--cronos-bg-primary` (#080A08)

| Status | Colour | Contrast vs bg-primary | Contrast vs bg-card | WCAG AA (4.5:1 text) |
|---|---|---|---|---|
| up | `#00C853` (reused accent) | 8.88 : 1 | 7.29 : 1 | Pass |
| down | `#FF6E6E` | 7.29 : 1 | 5.99 : 1 | Pass |
| degraded | `#FFC24B` | 12.36 : 1 | 10.15 : 1 | Pass |
| paused | `#9CA3AF` | 7.82 : 1 | 6.42 : 1 | Pass |

All four clear WCAG AA's 4.5:1 text threshold (and the looser 3:1 UI-component threshold) against
both background levels used in the system. `up` intentionally reuses the accent colour itself —
"all is well" should look like the brand, not a separate colour.

### Still open for Oryn

1. **Palette match vs. own accent** (SRS §17) — this proposal reuses the portfolio's green
   verbatim. Say the word if Cronos should take a different accent hue instead.
2. **Light theme** — proposed only as an unvalidated skeleton above. Confirm whether Day 5 should
   build it out or whether Cronos stays dark-only like the source site.
3. **Badge/pill styling** wasn't found on the sampled pages — if there's a specific "Open to
   Work"-style pill Oryn wants matched, point to the page/state it appears on and today's
   extraction script can be re-run against it.
4. **Glass blur value** for the floating navbar has no observed source — `blur(16px)` above is a
   placeholder, not an extracted value.
