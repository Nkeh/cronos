import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Docker Desktop on Windows can't always deliver native FS change events
// across a bind mount; WATCH_POLLING trades latency for reliability there.
const usePolling = process.env.WATCH_POLLING === 'true'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    // Reached only through Caddy on :8080, never a real external host.
    allowedHosts: true,
    hmr: {
      host: 'localhost',
      clientPort: 8080,
    },
    // interval bumped 300ms -> 1000ms and heavy/irrelevant trees excluded (docs/progress/
    // day-05c.md): the default cadence scanning the whole bind-mounted frontend/ tree, including
    // frontend/tests/screenshots (188 files), sustained ~20-40% idle CPU on this host. A
    // judgment-call trade of reload latency for CPU headroom, not a value with a specific target.
    watch: usePolling
      ? {
          usePolling: true,
          interval: 1000,
          ignored: [
            '**/node_modules/**',
            '**/dist/**',
            '**/tests/screenshots/**',
            '**/test-results/**',
          ],
        }
      : undefined,
  },
})
