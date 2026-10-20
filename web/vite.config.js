import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Every /api, the cooking photos, chat attachments and the card scans go to the
// Festin backend, which keeps them all beside its database. It rejects a write whose
// Origin is not its own host, so the proxy rewrites it.
// FESTIN_PORT lets each worker point at its own dev kitchen (default 8879).
const FESTIN = 'http://127.0.0.1:' + (process.env.FESTIN_PORT || '8879')

function rewriteOrigin(target) {
  return (proxy) => proxy.on('proxyReq', (req) => req.getHeader('origin') && req.setHeader('origin', target))
}

function to(target) {
  return { target, changeOrigin: true, configure: rewriteOrigin(target) }
}

export const proxy = {
  '/cards': { target: FESTIN, changeOrigin: true },
  '/photos': { target: FESTIN, changeOrigin: true },
  '/files': { target: FESTIN, changeOrigin: true },
  '/api': to(FESTIN),
}

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node' },
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
})
