import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Chat still talks to the live kitchen. Everything else in /api talks to Festin.
// Both apps reject a write whose Origin is not their own host, so the proxy rewrites it.
// More specific /api paths are registered first; connect matches in that order.
const LIVE = 'http://127.0.0.1:8876'
// FESTIN_PORT lets each worker point at its own dev kitchen (default 8879).
const FESTIN = 'http://127.0.0.1:' + (process.env.FESTIN_PORT || '8879')

function rewriteOrigin(target) {
  return (proxy) => proxy.on('proxyReq', (req) => req.getHeader('origin') && req.setHeader('origin', target))
}

function to(target) {
  return { target, changeOrigin: true, configure: rewriteOrigin(target) }
}

export const proxy = {
  '/cards': { target: LIVE, changeOrigin: true },
  '/photos': { target: LIVE, changeOrigin: true },
  // /api/chats must precede /api/chat: Vite matches the first prefix.
  '/api/chats': to(FESTIN),
  '/api/chat': to(LIVE),
  '/api/stop': to(LIVE),
  '/api/new-chat': to(LIVE),
  '/api/state': to(LIVE),
  '/api': to(FESTIN),
}

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node' },
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
})
