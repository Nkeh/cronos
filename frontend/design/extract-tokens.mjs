// Extracts design tokens from https://www.bonyaransom.me/ for Oryn's
// approval before Day 5 builds the real design system on top of them.
//
// Run inside the official Playwright image (has browsers preinstalled), via
// the `tools` Compose profile: `docker compose --profile tools run --rm playwright`.
//
// Does NOT copy the portfolio's source, images or font files — only reads
// computed styles / font family names / colour values from the rendered page.

import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REFERENCE_DIR = path.join(__dirname, 'reference')

const BASE_URL = 'https://www.bonyaransom.me'
const PAGES = ['/', '/about', '/projects', '/contact']
const VIEWPORTS = [
  { label: '375', width: 375, height: 1400 },
  { label: '1440', width: 1440, height: 1200 },
]
// Light and dark emulation produced byte-identical :root tokens on the first
// run (the site is dark-only, no theme toggle) — capturing both again would
// just double the screenshots for no new information, so only dark is kept.
const THEMES = ['dark']

const SAMPLE_SELECTORS = [
  'body',
  'h1',
  'h2',
  'h3',
  'p',
  'a',
  'button',
  'nav',
  'header',
  '[class*="badge" i]',
  '[class*="pill" i]',
  '[class*="card" i]',
]

/** @param {import('playwright').Page} page */
async function extractComputedStyles(page) {
  return page.evaluate((selectors) => {
    const pick = (cs) => ({
      fontFamily: cs.fontFamily,
      fontSize: cs.fontSize,
      fontWeight: cs.fontWeight,
      lineHeight: cs.lineHeight,
      letterSpacing: cs.letterSpacing,
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      borderRadius: cs.borderRadius,
      boxShadow: cs.boxShadow,
    })

    const out = {}
    for (const selector of selectors) {
      const el = document.querySelector(selector)
      out[selector] = el ? pick(getComputedStyle(el)) : null
    }
    return out
  }, SAMPLE_SELECTORS)
}

/** @param {import('playwright').Page} page */
async function extractRootCustomProperties(page) {
  return page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement)
    const props = {}
    for (const sheet of Array.from(document.styleSheets)) {
      let rules
      try {
        rules = sheet.cssRules
      } catch {
        continue // cross-origin stylesheet, can't read rules
      }
      for (const rule of Array.from(rules)) {
        if (rule.selectorText === ':root' && rule.style) {
          for (const name of Array.from(rule.style)) {
            if (name.startsWith('--')) props[name] = cs.getPropertyValue(name).trim()
          }
        }
      }
    }
    return props
  })
}

/** @param {import('playwright').Page} page */
async function extractFontFamilies(page) {
  return page.evaluate(async () => {
    try {
      await document.fonts.ready
    } catch {
      // ignore
    }
    const families = new Set()
    document.fonts.forEach((f) => families.add(f.family))
    return Array.from(families)
  })
}

/** @param {import('playwright').Page} page */
async function extractFrequencies(page) {
  return page.evaluate(() => {
    const colorCounts = new Map()
    const radiusCounts = new Map()
    const shadowCounts = new Map()
    const backdropCounts = new Map()
    const durationCounts = new Map()
    const easingCounts = new Map()

    const bump = (map, key) => {
      if (!key || key === 'none' || key === '0px' || key === 'normal') return
      map.set(key, (map.get(key) ?? 0) + 1)
    }

    for (const el of document.querySelectorAll('*')) {
      const cs = getComputedStyle(el)
      bump(colorCounts, cs.color)
      bump(colorCounts, cs.backgroundColor)
      bump(colorCounts, cs.borderColor)
      bump(radiusCounts, cs.borderRadius)
      bump(shadowCounts, cs.boxShadow)
      bump(backdropCounts, cs.backdropFilter)
      bump(durationCounts, cs.transitionDuration)
      bump(easingCounts, cs.transitionTimingFunction)
    }

    const topEntries = (map, n) =>
      Array.from(map.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, n)
        .map(([value, count]) => ({ value, count }))

    return {
      topColors: topEntries(colorCounts, 20),
      borderRadius: topEntries(radiusCounts, 10),
      boxShadow: topEntries(shadowCounts, 10),
      backdropFilter: topEntries(backdropCounts, 10),
      transitionDuration: topEntries(durationCounts, 10),
      transitionTimingFunction: topEntries(easingCounts, 10),
    }
  })
}

/** @param {import('playwright').Page} page */
async function extractKeyframeNames(page) {
  return page.evaluate(() => {
    const names = new Set()
    for (const sheet of Array.from(document.styleSheets)) {
      let rules
      try {
        rules = sheet.cssRules
      } catch {
        continue // cross-origin stylesheet, can't read rules
      }
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSKeyframesRule) names.add(rule.name)
      }
    }
    return Array.from(names)
  })
}

/** @param {import('playwright').Page} page */
async function detectThemeToggle(page) {
  return page.evaluate(() => {
    const candidates = document.querySelectorAll(
      '[aria-label*="theme" i], [data-theme-toggle], [class*="theme-toggle" i], button[class*="theme" i]',
    )
    return candidates.length > 0
  })
}

async function main() {
  await mkdir(REFERENCE_DIR, { recursive: true })

  const browser = await chromium.launch()
  const extracted = {
    source: BASE_URL,
    extractedAt: new Date().toISOString(),
    themeToggleDetected: null,
    pages: {},
  }
  const errors = []

  for (const pagePath of PAGES) {
    extracted.pages[pagePath] = {}

    for (const viewport of VIEWPORTS) {
      extracted.pages[pagePath][viewport.label] = {}

      for (const theme of THEMES) {
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: theme,
        })
        const page = await context.newPage()

        try {
          await page.goto(`${BASE_URL}${pagePath}`, { waitUntil: 'networkidle', timeout: 30_000 })

          if (extracted.themeToggleDetected === null) {
            extracted.themeToggleDetected = await detectThemeToggle(page)
          }

          const screenshotName = `${pagePath === '/' ? 'home' : pagePath.replaceAll('/', '')}-${viewport.label}-${theme}.jpg`
          await page.screenshot({
            path: path.join(REFERENCE_DIR, screenshotName),
            fullPage: true,
            type: 'jpeg',
            quality: 75,
          })

          const [computedStyles, rootVars, fonts, frequencies, keyframes] = await Promise.all([
            extractComputedStyles(page),
            extractRootCustomProperties(page),
            extractFontFamilies(page),
            extractFrequencies(page),
            extractKeyframeNames(page),
          ])

          extracted.pages[pagePath][viewport.label][theme] = {
            screenshot: `reference/${screenshotName}`,
            computedStyles,
            rootCustomProperties: rootVars,
            fontFamilies: fonts,
            frequencies,
            keyframeNames: keyframes,
          }
        } catch (err) {
          errors.push({ page: pagePath, viewport: viewport.label, theme, error: String(err) })
          extracted.pages[pagePath][viewport.label][theme] = { error: String(err) }
        } finally {
          await context.close()
        }
      }
    }
  }

  await browser.close()

  extracted.extractionErrors = errors
  await writeFile(
    path.join(__dirname, 'extracted.json'),
    JSON.stringify(extracted, null, 2),
    'utf8',
  )

  console.log(`Wrote extracted.json with ${errors.length} extraction error(s).`)
  if (errors.length > 0) {
    console.log('Errors:', JSON.stringify(errors, null, 2))
  }
}

main().catch((err) => {
  console.error(err)
  process.exitCode = 1
})
