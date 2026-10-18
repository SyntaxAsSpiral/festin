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
  it('keeps chat on the live kitchen and sends the card api to Festin', () => {
    expect(targetFor('/api/chat')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/api/stop')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/api/new-chat')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/api/state')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/cards/x.jpg')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/photos/x.jpg')).toBe('http://127.0.0.1:8876')
    expect(targetFor('/api/chats')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/chats/abc')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/recipes')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/notes/n')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/plans/2026-10-17')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/session')).toBe('http://127.0.0.1:8879')
    expect(targetFor('/api/settings')).toBe('http://127.0.0.1:8879')
  })
})
