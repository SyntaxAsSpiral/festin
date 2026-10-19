/** Speak API helpers for the Listen control. */

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * POST /api/speak then poll GET url?status=1 until ready.
 * Returns an HTMLAudioElement pointed at the wav.
 */
export async function prepareVoice(text) {
  let res = await fetch('/api/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ text }),
  })
  let body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || 'The voice could not be rendered.')
  const url = body.url
  if (!url) throw new Error('The voice could not be rendered.')
  while (body.status === 'rendering') {
    await pause(2000)
    res = await fetch(url + (url.includes('?') ? '&' : '?') + 'status=1', {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    body = await res.json().catch(() => ({}))
    if (res.status === 202) continue
    if (!res.ok) throw new Error(body.error || 'The voice could not be rendered.')
  }
  return new Audio(url)
}

export function benignMediaAbort(error) {
  return (
    error?.name === 'AbortError' ||
    /fetching process for the media resource was aborted/i.test(String(error?.message || ''))
  )
}

/** True when the voice plugin is on in a GET /api/plugins payload. */
export function voiceIsOn(plugins) {
  if (!plugins) return false
  const list = Array.isArray(plugins) ? plugins : plugins.plugins || plugins.items
  if (!Array.isArray(list)) return false
  const voice = list.find((p) => (p.id || '').toLowerCase() === 'voice')
  return Boolean(voice && (voice.enabled ?? voice.on ?? voice.active))
}
