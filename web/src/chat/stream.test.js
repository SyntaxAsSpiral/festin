import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadKitchenChat } from './stream.js'

function respond(routes) {
  return vi.fn(async (url) => {
    const body = routes[url]
    if (body === undefined) return new Response('{}', { status: 404, headers: { 'content-type': 'application/json' } })
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('loading this device\'s chat', () => {
  it('reads the session chat, its messages and the model for the header', async () => {
    vi.stubGlobal('fetch', respond({
      '/api/session': { chat_id: 'c1' },
      '/api/settings': { model: { name: 'anthropic/claude-haiku', baseUrl: 'https://openrouter.ai/api/v1' } },
      '/api/chats/c1': { id: 'c1', messages: [{ role: 'user', content: 'hi' }] },
    }))
    expect(await loadKitchenChat()).toEqual({
      chatId: 'c1',
      messages: [{ role: 'user', content: 'hi' }],
      model: 'anthropic/claude-haiku',
      host: 'openrouter.ai',
      wetBand: 45,
    })
  })
  it('starts empty when the device has no chat yet', async () => {
    vi.stubGlobal('fetch', respond({ '/api/session': { chat_id: null }, '/api/settings': {} }))
    expect(await loadKitchenChat()).toEqual({ chatId: null, messages: [], model: '', host: '', wetBand: 45 })
  })
})
