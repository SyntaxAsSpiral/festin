// Chat transport: this device's chat on the Festin backend.
import { readJson } from '../backend.js'
import { clampWetBand } from './ink/constants.js'

// Fired on window when this device's session moves to another chat.
export const CHAT_SESSION_EVENT = 'festin-chat-session'

async function postJson(path, body, signal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    /* empty or not JSON */
  }
  if (!res.ok) throw Object.assign(new Error(data?.error || 'Request failed (' + res.status + ')'), { status: res.status })
  return data
}

// Feed each NDJSON line to onEvent. A line split across chunks waits for its end.
export async function readNdjson(reader, onEvent) {
  const decoder = new TextDecoder()
  let carry = ''
  for (;;) {
    const { value, done } = await reader.read()
    carry += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = carry.split('\n')
    carry = done ? '' : lines.pop()
    for (const line of lines) {
      const text = line.trim()
      if (!text) continue
      let event
      try {
        event = JSON.parse(text)
      } catch {
        continue
      }
      if (event && typeof event.type === 'string') onEvent(event)
    }
    if (done) return
  }
}

// POST /api/chat as a stream. Every outcome arrives through onEvent, including a
// 409 or 400 answered as plain JSON before any stream starts.
export async function sendChat(body, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  })
  const type = res.headers.get('content-type') || ''
  if (!type.includes('application/x-ndjson')) {
    let error = null
    try {
      error = (await res.json())?.error
    } catch {
      /* not JSON */
    }
    onEvent({ type: 'error', status: res.status, error: error || 'Request failed (' + res.status + ')' })
    return
  }
  await readNdjson(res.body.getReader(), onEvent)
}

export function stopChat({ requestId, submissionId }) {
  return postJson('/api/stop', { request_id: requestId, submission_id: submissionId })
}

// A fresh chat for this device; the backend files the previous one into Chats.
export function newChat() {
  return postJson('/api/chats', {})
}

function hostOf(url) {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}

// What the chat needs: this device's chat (from its session), its messages, and
// the model for the header. A device with no chat yet gets one on its first message.
export async function loadKitchenChat() {
  const [session, settings] = await Promise.all([readJson('/api/session'), readJson('/api/settings')])
  const chatId = session?.chat_id || null
  const chat = chatId ? await readJson('/api/chats/' + encodeURIComponent(chatId)).catch(() => null) : null
  return {
    chatId,
    messages: chat?.messages || [],
    model: settings?.model?.name || '',
    host: hostOf(settings?.model?.baseUrl || ''),
    wetBand: clampWetBand(settings?.chatWetBand),
  }
}
