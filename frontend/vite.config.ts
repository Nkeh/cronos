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
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
  },
})
