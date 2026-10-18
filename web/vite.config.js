import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Chat and live boot still talk to the live kitchen on :8876.
// Settings and plugins talk to the Festin server on :8879 (this bead).
// Both reject a write whose Origin is not their own host, so the proxy rewrites it.
const LIVE = 'http://127.0.0.1:8876'
const FESTIN = 'http://127.0.0.1:8886'

function rewriteOrigin(target) {
  return (proxy) => proxy.on('proxyReq', (req) => req.getHeader('origin') && req.setHeader('origin', target))
}

function to(target) {
  return { target, changeOrigin: true, configure: rewriteOrigin(target) }
}

export const proxy = {
  '/cards': { target: LIVE, changeOrigin: true },
  '/photos': { target: LIVE, changeOrigin: true },
  '/api/settings': to(FESTIN),
  '/api/plugins': to(FESTIN),
  '/api/notes': to(FESTIN),
  '/api': to(LIVE),
}

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node' },
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
})
