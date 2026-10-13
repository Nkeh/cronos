// Builds one HTML-grid contact sheet per page (reading frontend/tests/screenshots/<page>/*.png)
// and screenshots each grid into a single PNG for quick review. Run after screenshots.spec.ts.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const screenshotsDir = path.join(__dirname, '..', 'screenshots')
const outDir = path.join(screenshotsDir, 'contact-sheets')
fs.mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage()

const pageDirs = fs
  .readdirSync(screenshotsDir)
  .filter((name) => name !== 'contact-sheets')
  .filter((name) => fs.statSync(path.join(screenshotsDir, name)).isDirectory())

for (const pageName of pageDirs) {
  const dir = path.join(screenshotsDir, pageName)
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.png'))
    .sort()
  if (files.length === 0) continue

  const html = `<!doctype html><html><body style="margin:0;background:#111;font-family:monospace;">
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:8px;">
      ${files
        .map(
          (f) => `<div>
            <div style="color:#fff;font-size:11px;margin-bottom:4px;">${f}</div>
            <img src="file://${path.join(dir, f).replace(/\\/g, '/')}" style="width:100%;border:1px solid #444;" />
          </div>`,
        )
        .join('\n')}
    </div>
  </body></html>`

  const htmlPath = path.join(outDir, `${pageName}.html`)
  fs.writeFileSync(htmlPath, html)
  await page.goto(`file://${htmlPath.replace(/\\/g, '/')}`)
  await page.setViewportSize({ width: 1600, height: 1200 })
  await page.screenshot({ path: path.join(outDir, `${pageName}.png`), fullPage: true })
  console.log(`contact sheet: ${pageName}.png`)
}

await browser.close()
