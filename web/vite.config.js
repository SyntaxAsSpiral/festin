import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Every /api and the cooking photos go to the Festin backend. Card scans (2.6 GB)
// still come from the live kitchen's files until the switchover copies them over.
// Both apps reject a write whose Origin is not their own host, so the proxy rewrites it.
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
  '/photos': { target: FESTIN, changeOrigin: true },
  '/api': to(FESTIN),
}

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node' },
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
})
