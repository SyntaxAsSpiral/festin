import { useRef, useState } from 'react'

const MAX_PHOTOS = 4
const MAX_BYTES = 10 * 1024 * 1024

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read ' + file.name))
    reader.readAsDataURL(file)
  })
}

export function Composer({ chat }) {
  const { turn } = chat
  const [photos, setPhotos] = useState([])
  const [note, setNote] = useState('')
  const picker = useRef(null)
  const busy = turn.phase === 'thinking' || turn.phase === 'revealing'
  const idle = turn.phase === 'idle' || turn.phase === 'composing'

  function submit() {
    if (busy) return
    chat.send(photos.map((p) => p.data))
    setPhotos([])
    setNote('')
  }

  async function addPhotos(files) {
    setNote('')
    const next = [...photos]
    for (const file of files) {
      if (next.length >= MAX_PHOTOS) return setNote('Attach up to four photos per message.')
      if (file.size > MAX_BYTES) return setNote('Each photo must be under 10 MB.')
      next.push({ name: file.name, data: await readAsDataUrl(file) })
    }
    setPhotos(next)
  }

  return (
    <div className="composer">
      {turn.phase === 'failed' && (
        <div className="failed" role="alert">
          <p>{turn.error?.message}</p>
          <button type="button" onClick={chat.retry}>
            Retry
          </button>
          <button type="button" onClick={chat.dismiss}>
            Dismiss
          </button>
        </div>
      )}
      {photos.length > 0 && (
        <ul className="attachments">
          {photos.map((p, i) => (
            <li key={i}>
              {p.name}
              <button type="button" aria-label={'Remove ' + p.name} onClick={() => setPhotos(photos.filter((_, j) => j !== i))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {note && <p className="composer-note">{note}</p>}
      <textarea
        id="ask"
        rows={2}
        placeholder="Ask Babette…"
        value={turn.draft}
        onChange={(event) => chat.type(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="composer-bar">
        <button type="button" id="bPhoto" onClick={() => picker.current?.click()} disabled={busy}>
          +photo
        </button>
        <input
          ref={picker}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(event) => {
            addPhotos([...event.target.files]).catch((err) => setNote(err.message))
            event.target.value = ''
          }}
        />
        <button type="button" id="bChat" onClick={() => chat.newChat().catch((err) => setNote(err.message))} disabled={!idle}>
          +chat
        </button>
        {busy ? (
          <button type="button" className="send stop" onClick={chat.stop}>
            Stop
          </button>
        ) : (
          <button type="button" className="send" onClick={submit} disabled={!turn.draft.trim() && !photos.length}>
            Send
          </button>
        )}
      </div>
    </div>
  )
}
