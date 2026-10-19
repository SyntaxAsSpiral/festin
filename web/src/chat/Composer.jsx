import { useRef, useState } from 'react'

const MAX_PHOTOS = 4
const MAX_BYTES = 10 * 1024 * 1024
const TEXT_TYPES = new Set(['text/plain', 'text/markdown', ''])
const TEXT_EXT = /\.(md|markdown|txt|text)$/i

async function readAsDataUrl(file) {
  if (typeof file.arrayBuffer === 'function') {
    const bytes = new Uint8Array(await file.arrayBuffer())
    let binary = ''
    for (const byte of bytes) binary += String.fromCharCode(byte)
    const mime = file.type || 'application/octet-stream'
    return 'data:' + mime + ';base64,' + btoa(binary)
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read ' + file.name))
    reader.readAsDataURL(file)
  })
}

async function readAsText(file) {
  if (typeof file.text === 'function') {
    return file.text()
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read ' + file.name))
    reader.readAsText(file, 'utf-8')
  })
}

function isImage(file) {
  return String(file.type || '').startsWith('image/')
}

function isTextDoc(file) {
  const type = String(file.type || '')
  if (type.startsWith('image/')) return false
  if (TEXT_TYPES.has(type)) return true
  return TEXT_EXT.test(file.name || '')
}

/** Pure helper for vitest: classify a File-like and build the next attachment lists. */
export async function collectAttachments(current, incoming, { maxPhotos = MAX_PHOTOS, maxBytes = MAX_BYTES } = {}) {
  const photos = [...(current.photos || [])]
  const files = [...(current.files || [])]
  let note = ''
  for (const file of incoming) {
    if (isImage(file)) {
      if (photos.length >= maxPhotos) {
        note = 'Attach up to four photos per message.'
        break
      }
      if (file.size > maxBytes) {
        note = 'Each photo must be under 10 MB.'
        break
      }
      photos.push({ name: file.name, data: await readAsDataUrl(file) })
      continue
    }
    if (isTextDoc(file)) {
      let text
      try {
        text = await readAsText(file)
      } catch {
        note = 'That file is not valid UTF-8 text.'
        break
      }
      if (typeof text !== 'string' || text.includes('\u0000')) {
        note = 'That file is not valid UTF-8 text.'
        break
      }
      files.push({ name: file.name, text })
      continue
    }
    note = 'Attach an image, or a .md / .txt document.'
    break
  }
  return { photos, files, note }
}

export function Composer({ chat }) {
  const { turn } = chat
  const [photos, setPhotos] = useState([])
  const [files, setFiles] = useState([])
  const [note, setNote] = useState('')
  const picker = useRef(null)
  const busy = turn.phase === 'thinking' || turn.phase === 'revealing'
  const idle = turn.phase === 'idle' || turn.phase === 'composing'

  function submit() {
    if (busy) return
    chat.send(
      photos.map((p) => p.data),
      files.map((f) => ({ name: f.name, text: f.text })),
    )
    setPhotos([])
    setFiles([])
    setNote('')
  }

  async function addFiles(list) {
    setNote('')
    const next = await collectAttachments({ photos, files }, list)
    setPhotos(next.photos)
    setFiles(next.files)
    if (next.note) setNote(next.note)
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
      {(photos.length > 0 || files.length > 0) && (
        <ul className="attachments">
          {photos.map((p, i) => (
            <li key={'p' + i} className="att-photo">
              <img src={p.data} alt="" />
              <span>{p.name}</span>
              <button
                type="button"
                aria-label={'Remove ' + p.name}
                onClick={() => setPhotos(photos.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </li>
          ))}
          {files.map((f, i) => (
            <li key={'f' + i} className="att-file">
              <span className="att-chip">{f.name}</span>
              <button
                type="button"
                aria-label={'Remove ' + f.name}
                onClick={() => setFiles(files.filter((_, j) => j !== i))}
              >
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
        <button type="button" id="bFile" onClick={() => picker.current?.click()} disabled={busy}>
          +file
        </button>
        <input
          ref={picker}
          type="file"
          accept="image/*,.md,.txt,text/plain,text/markdown"
          multiple
          hidden
          onChange={(event) => {
            addFiles([...event.target.files]).catch((err) => setNote(err.message))
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
          <button
            type="button"
            className="send"
            onClick={submit}
            disabled={!turn.draft.trim() && !photos.length && !files.length}
          >
            Send
          </button>
        )}
      </div>
    </div>
  )
}
