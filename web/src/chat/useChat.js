import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { liveState, reloadLiveState } from '../backend.js'
import { newChat, sendChat, stopChat } from './stream.js'
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

function hostOf(url) {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}

// The chat on the live kitchen: transcript, turn machine, and the actions on it.
export function useChat() {
  const [kitchen, setKitchen] = useState(null)
  const [turn, dispatch] = useReducer(turnReducer, undefined, startTurn)
  const flight = useRef(null)

  useEffect(() => {
    let gone = false
    liveState().then((body) => !gone && setKitchen(body), () => {})
    return () => {
      gone = true
      flight.current?.abort()
    }
  }, [])

  useEffect(() => saveDraft(turn.draft), [turn.draft])

  // Reveal runs on animation frames only while there is text to show.
  const revealing = turn.phase === 'revealing'
  useEffect(() => {
    if (!revealing) return undefined
    let last = performance.now()
    let frame = requestAnimationFrame(function tick(now) {
      dispatch({ type: 'tick', dt: now - last })
      last = now
      frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  }, [revealing])

  // A finished or failed turn reloads the transcript; a settled reply then hands over to it.
  const reload = useCallback(() => reloadLiveState().then(setKitchen), [])
  useEffect(() => {
    if (turn.phase === 'settled') reload().then(() => dispatch({ type: 'absorbed' }), () => dispatch({ type: 'absorbed' }))
    else if (turn.phase === 'failed') reload().catch(() => {})
  }, [turn.phase, reload])

  const run = useCallback(
    (sent) => {
      const state = kitchen?.state
      const control = new AbortController()
      flight.current = control
      const body = {
        text: sent.text,
        week: kitchen?.thisWeek,
        photos: sent.photos,
        plan: null,
        chat_id: state?.activeChatId,
        expected_messages: state?.messages?.length,
        submission_id: sent.submissionId,
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
    (photos = []) => {
      const text = turn.draft.trim()
      if (!text && !photos.length) return
      dispatch({ type: 'send', text: text || 'Let’s talk about this dish.', photos, submissionId: crypto.randomUUID() })
    },
    [turn.draft],
  )

  const stop = useCallback(() => {
    stopChat({ requestId: turn.requestId, submissionId: turn.sent?.submissionId }).catch(() => {})
  }, [turn.requestId, turn.sent])

  const startNewChat = useCallback(async () => {
    if (turn.phase !== 'idle' && turn.phase !== 'composing') return
    await newChat(kitchen?.state?.activeChatId)
    await reload()
  }, [turn.phase, kitchen, reload])

  const settings = kitchen?.state?.settings
  return {
    ready: Boolean(kitchen),
    messages: kitchen?.state?.messages || [],
    model: settings?.model || '',
    host: hostOf(settings?.base_url),
    turn,
    type: (draft) => dispatch({ type: 'type', draft }),
    send,
    stop,
    retry: () => dispatch({ type: 'retry' }),
    dismiss: () => dispatch({ type: 'dismiss' }),
    newChat: startNewChat,
  }
}
