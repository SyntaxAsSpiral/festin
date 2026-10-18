import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy to the live kitchen. The dev server and preview both use it.
// Live only accepts writes whose Origin matches its own host.
const LIVE = 'http://127.0.0.1:8876'
const live = {
  '/cards': { target: LIVE, changeOrigin: true },
  '/photos': { target: LIVE, changeOrigin: true },
  '/api': {
    target: LIVE,
    changeOrigin: true,
    configure: (proxy) => proxy.on('proxyReq', (req) => req.getHeader('origin') && req.setHeader('origin', LIVE)),
  },
}

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node' },
  server: { host: '127.0.0.1', port: 5173, proxy: live },
  preview: { host: '127.0.0.1', port: 4173, proxy: live },
})
