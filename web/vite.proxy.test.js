import { describe, expect, it } from 'vitest'
import { proxy } from './vite.config.js'

// Vite walks proxy keys in order and uses the first prefix match.
function targetFor(url) {
  for (const context of Object.keys(proxy)) {
    if (url.startsWith(context)) return proxy[context].target
  }
  return null
}

describe('dev proxy', () => {
  it('sends every api call, chat included, and the cooking photos to Festin; scans still come from live', () => {
    for (const url of ['/api/chat', '/api/stop', '/api/chats', '/api/chats/abc', '/api/recipes', '/api/notes/n', '/api/plans/2026-10-17', '/api/session', '/api/settings']) {
      expect(targetFor(url)).toBe('http://127.0.0.1:8879')
    }
    expect(targetFor('/cards/x.jpg')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/photos/x.jpg')).toBe('http://127.0.0.1:8879')
  })
})
