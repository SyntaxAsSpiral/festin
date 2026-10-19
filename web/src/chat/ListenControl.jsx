import { useEffect, useRef, useState } from 'react'
import { benignMediaAbort, prepareVoice } from './listen.js'

const heard = new Map()

function ListenIcon() {
  return (
    <svg className="listen-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d="M5 9v6h4l5 4V5L9 9H5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M17 9a4 4 0 0 1 0 6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M19.5 6.5a8 8 0 0 1 0 11" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

/**
 * Quiet Listen control on a finished assistant reply.
 * States: idle (Listen) → preparing → playing (Stop) → error line.
 */
export function ListenControl({ text }) {
  const [label, setLabel] = useState('Listen')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  async function onClick() {
    setError('')
    let audio = heard.get(text)
    if (audio && !(audio instanceof Promise) && !audio.paused) {
      audio.pause()
      setLabel('Listen')
      return
    }
    if (audio && !(audio instanceof Promise) && audio.ended) audio.currentTime = 0
    setBusy(true)
    if (!(audio && !(audio instanceof Promise))) setLabel('Preparing…')
    try {
      if (!audio) {
        const pending = prepareVoice(text)
        heard.set(text, pending)
        try {
          audio = await pending
          heard.set(text, audio)
        } catch (err) {
          if (heard.get(text) === pending) heard.delete(text)
          throw err
        }
        audio.onended = () => {
          if (mounted.current) setLabel('Listen')
        }
      } else if (audio instanceof Promise) {
        audio = await audio
      }
      if (!mounted.current) return
      setLabel('Stop')
      await audio.play()
    } catch (err) {
      if (mounted.current) {
        setLabel('Listen')
        if (!benignMediaAbort(err)) setError(String(err?.message || err || 'The voice could not be rendered.'))
      }
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  return (
    <div className="listen-wrap">
      <button type="button" className="listen" disabled={busy && label === 'Preparing…'} onClick={onClick}>
        {label === 'Listen' ? (
          <>
            <ListenIcon /> Listen
          </>
        ) : (
          label
        )}
      </button>
      {error ? (
        <p className="listen-error" role="status">
          {error}
        </p>
      ) : null}
    </div>
  )
}
