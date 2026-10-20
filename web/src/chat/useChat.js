import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { prefersReducedMotion } from '../useReducedMotion.js'
import { ensureSeepStyles } from './ink/seep.js'
import { readWritingSpeed } from './ink/speed.js'
import { newId } from '../secure.js'
import { CHAT_SESSION_EVENT, loadKitchenChat, newChat, sendChat, stopChat } from './stream.js'
import { initialTurn, turnReducer } from './turn.js'

const DRAFT_KEY = 'festin.draft'

function loadDraft() {
  try {
    return localStorage.getItem(DRAFT_KEY) || ''
  } catch {
    return ''
  }
}

function saveDraft(text) {
  try {
    if (text) localStorage.setItem(DRAFT_KEY, text)
    else localStorage.removeItem(DRAFT_KEY)
  } catch {
    /* storage unavailable; the draft lives only in memory */
  }
}

function startTurn() {
  const draft = loadDraft()
  return { ...initialTurn, draft, phase: draft.trim() ? 'composing' : 'idle' }
}

// This device's chat: transcript, turn machine, and the actions on it.
export function useChat(context = null) {
  const [kitchen, setKitchen] = useState(null)
  const [turn, dispatch] = useReducer(turnReducer, undefined, startTurn)
  const flight = useRef(null)
  // The context at the moment of sending, not at render: read through a ref.
  const looking = useRef(context)
  looking.current = context

  // The seep masks and keyframes exist before the first reply, so trace steps
  // that arrive while Babette thinks seep in as they land, not all at once later.
  useEffect(() => {
    void ensureSeepStyles()
  }, [])

  useEffect(() => {
    let gone = false
    loadKitchenChat().then((next) => !gone && setKitchen(next), () => {})
    // Reopening a filed chat points the session at it elsewhere (a chat card);
    // the panel then loads that chat instead of keeping the one it started with.
    const onSession = () => loadKitchenChat().then((next) => !gone && setKitchen(next), () => {})
    window.addEventListener(CHAT_SESSION_EVENT, onSession)
    return () => {
      gone = true
      window.removeEventListener(CHAT_SESSION_EVENT, onSession)
      flight.current?.abort()
    }
  }, [])

  useEffect(() => saveDraft(turn.draft), [turn.draft])

  // Ghost typist runs on animation frames while there is text to show.
  const revealing = turn.phase === 'revealing'
  useEffect(() => {
    if (!revealing) return undefined
    let frame = requestAnimationFrame(function tick(now) {
      const instant = prefersReducedMotion()
      dispatch({ type: 'tick', now, cps: readWritingSpeed(), instant })
      frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  }, [revealing])

  // A finished or failed turn reloads the transcript; a settled reply then hands over to it.
  const reload = useCallback(() => loadKitchenChat().then(setKitchen), [])
  useEffect(() => {
    if (turn.phase === 'settled') reload().then(() => dispatch({ type: 'absorbed' }), () => dispatch({ type: 'absorbed' }))
    else if (turn.phase === 'failed') reload().catch(() => {})
  }, [turn.phase, reload])

  const run = useCallback(
    (sent) => {
      const control = new AbortController()
      flight.current = control
      // The backend picks the household's current week; a device with no chat
      // yet gets one with its first message.
      const body = {
        text: sent.text,
        photos: sent.photos,
        files: sent.files,
        plan: null,
        chat_id: kitchen?.chatId || undefined,
        expected_messages: kitchen?.chatId ? kitchen.messages.length : undefined,
        submission_id: sent.submissionId,
        context: looking.current,
      }
      sendChat(body, (event) => dispatch({ type: 'event', event }), control.signal)
        .catch((err) => {
          if (err?.name === 'AbortError') return
          dispatch({ type: 'event', event: { type: 'error', error: 'The kitchen did not answer. Check the connection, then retry.' } })
        })
        .finally(() => {
          if (flight.current === control) flight.current = null
        })
    },
    [kitchen],
  )

  // Turn changes that need the network follow the machine, so a stale click can't double-send.
  const lastRun = useRef(0)
  useEffect(() => {
    if (turn.phase !== 'thinking' || !turn.sent || lastRun.current === turn.attempt) return
    lastRun.current = turn.attempt
    run(turn.sent)
  }, [turn.phase, turn.sent, turn.attempt, run])

  const send = useCallback(
    (photos = [], files = []) => {
      const text = turn.draft.trim()
      if (!text && !photos.length && !files.length) return
      dispatch({
        type: 'send',
        text: text || (files.length ? 'Please read the attached file.' : 'Let’s talk about this dish.'),
        photos,
        files,
        submissionId: newId(),
      })
    },
    [turn.draft],
  )

  const stop = useCallback(() => {
    stopChat({ requestId: turn.requestId, submissionId: turn.sent?.submissionId }).catch(() => {})
  }, [turn.requestId, turn.sent])

  const startNewChat = useCallback(async () => {
    if (turn.phase !== 'idle' && turn.phase !== 'composing') return
    await newChat()
    await reload()
  }, [turn.phase, reload])

  return {
    ready: Boolean(kitchen),
    messages: kitchen?.messages || [],
    model: kitchen?.model || '',
    host: kitchen?.host || '',
    turn,
    type: (draft) => dispatch({ type: 'type', draft }),
    send,
    stop,
    retry: () => dispatch({ type: 'retry' }),
    dismiss: () => dispatch({ type: 'dismiss' }),
    newChat: startNewChat,
  }
}
