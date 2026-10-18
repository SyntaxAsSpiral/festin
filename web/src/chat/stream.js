// Chat transport. Talks to the live kitchen until the Festin backend serves chat.

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

export function newChat(expectedChatId) {
  return postJson('/api/new-chat', { expected_chat_id: expectedChatId })
}
