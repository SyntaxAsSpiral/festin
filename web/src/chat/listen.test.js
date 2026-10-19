import { afterEach, describe, expect, it, vi } from 'vitest'
import { benignMediaAbort, prepareVoice, voiceIsOn } from './listen.js'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('voiceIsOn', () => {
  it('reads enabled from the plugins list', () => {
    expect(voiceIsOn(null)).toBe(false)
    expect(voiceIsOn({ plugins: [{ id: 'voice', enabled: false }] })).toBe(false)
    expect(voiceIsOn({ plugins: [{ id: 'voice', enabled: true }] })).toBe(true)
    expect(voiceIsOn([{ id: 'printer', enabled: true }])).toBe(false)
  })
})

describe('prepareVoice', () => {
  it('posts, polls while rendering, then returns an Audio for the url', async () => {
    const calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, init) => {
        calls.push({ url: String(url), method: init?.method || 'GET' })
        if (String(url) === '/api/speak' && init?.method === 'POST') {
          return {
            ok: true,
            status: 202,
            json: async () => ({ status: 'rendering', url: '/api/speak/abc' }),
          }
        }
        if (String(url).startsWith('/api/speak/abc')) {
          if (calls.filter((c) => c.url.includes('status=1')).length < 2) {
            return { ok: true, status: 202, json: async () => ({ status: 'rendering' }) }
          }
          return { ok: true, status: 200, json: async () => ({ status: 'ready', url: '/api/speak/abc' }) }
        }
        throw new Error('unexpected ' + url)
      }),
    )
    class FakeAudio {
      constructor(src) {
        this.src = src
      }
    }
    vi.stubGlobal('Audio', FakeAudio)
    vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn) => {
      fn()
      return 0
    })

    const audio = await prepareVoice('Bonjour.')
    expect(audio).toBeInstanceOf(FakeAudio)
    expect(audio.src).toBe('/api/speak/abc')
    expect(calls[0]).toMatchObject({ url: '/api/speak', method: 'POST' })
    expect(calls.some((c) => c.url.includes('status=1'))).toBe(true)
  })

  it('surfaces a polite error from a failed POST', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 400,
        json: async () => ({ error: 'Babette is already preparing another reading.' }),
      })),
    )
    await expect(prepareVoice('Hi.')).rejects.toThrow(/already preparing/)
  })
})

describe('benignMediaAbort', () => {
  it('treats AbortError as quiet', () => {
    expect(benignMediaAbort({ name: 'AbortError' })).toBe(true)
    expect(benignMediaAbort({ message: 'boom' })).toBe(false)
  })
})
