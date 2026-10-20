// Chat Turn machine (state-machine.md §2.4, §8.4 Turn). Pure: no fetch, no timers.
import { DEFAULT_TYPE_CPS } from './ink/constants.js'
import { typistTick } from './ink/typist.js'

export const initialTurn = {
  phase: 'idle', // idle | composing | thinking | revealing | settled | failed
  draft: '',
  sent: null, // { text, photos, files, submissionId } of the message in flight, kept for retry
  requestId: null,
  text: '', // reply received so far
  shown: 0, // characters the ghost typist has struck (integer)
  nextKey: 0, // performance.now()-style time the next keystroke is due
  done: false, // server said done; settle when the buffer drains
  trace: null,
  error: null,
  attempt: 0, // bumps on each send and retry; the network follows it
}

function afterReply(state) {
  return state.draft.trim() ? 'composing' : 'idle'
}

function clearReveal(extra = {}) {
  return { text: '', shown: 0, nextKey: 0, done: false, trace: null, requestId: null, ...extra }
}

export function turnReducer(state, action) {
  switch (action.type) {
    case 'type': {
      if (state.phase === 'thinking' || state.phase === 'revealing') return { ...state, draft: action.draft }
      if (state.phase === 'failed') return { ...state, draft: action.draft }
      return { ...state, draft: action.draft, phase: action.draft.trim() ? 'composing' : 'idle' }
    }
    case 'send': {
      if (state.phase !== 'composing' && state.phase !== 'idle' && state.phase !== 'settled') return state
      return {
        ...initialTurn,
        phase: 'thinking',
        draft: '',
        attempt: state.attempt + 1,
        sent: {
          text: action.text,
          photos: action.photos || [],
          files: action.files || [],
          submissionId: action.submissionId,
        },
      }
    }
    case 'retry': {
      if (state.phase !== 'failed' || !state.sent) return state
      return { ...state, phase: 'thinking', attempt: state.attempt + 1, error: null, ...clearReveal() }
    }
    case 'dismiss': {
      if (state.phase !== 'failed') return state
      // The unsent message goes back into the composer so nothing typed is lost.
      const draft = state.draft.trim() ? state.draft : state.sent?.text || ''
      return { ...initialTurn, attempt: state.attempt, draft, phase: draft.trim() ? 'composing' : 'idle' }
    }
    case 'event':
      return onEvent(state, action.event)
    case 'tick': {
      if (state.phase !== 'revealing') return state
      // Reduced motion: show everything received, no typist animation.
      if (action.instant) {
        const shown = state.text.length
        if (state.done) return { ...state, shown, phase: 'settled' }
        if (state.shown === shown) return state
        return { ...state, shown }
      }
      const cps = action.cps ?? DEFAULT_TYPE_CPS
      const now = action.now ?? 0
      const typed = typistTick(
        { lit: state.shown, nextKey: state.nextKey, cps, rng: action.rng },
        { received: state.text.length, text: state.text, now },
      )
      const shown = typed.lit
      const nextKey = typed.nextKey
      if (state.done && shown >= state.text.length) {
        return { ...state, shown, nextKey, phase: 'settled' }
      }
      // Same shown, nextKey, and phase: the frame typed nothing. Once the
      // typist has caught the buffer, the schedule clamp slides nextKey to
      // now every frame; that is not a new stroke, so keep this object and
      // let the next tick apply the clamp when text actually arrives.
      if (shown === state.shown && (nextKey === state.nextKey || shown >= state.text.length)) return state
      return { ...state, shown, nextKey }
    }
    case 'absorbed': {
      // The settled reply is now in the reloaded transcript.
      if (state.phase !== 'settled') return state
      return { ...state, phase: afterReply(state), sent: null, ...clearReveal() }
    }
    default:
      return state
  }
}

function onEvent(state, event) {
  if (state.phase !== 'thinking' && state.phase !== 'revealing') return state
  switch (event.type) {
    case 'start':
      return { ...state, requestId: event.request_id || null }
    case 'delta': {
      const text = state.text + (event.text || '')
      return { ...state, text, phase: 'revealing' }
    }
    case 'reset':
      return { ...state, text: '', shown: 0, nextKey: 0 }
    case 'trace':
      return { ...state, trace: event.trace ?? null }
    case 'done':
      if (state.phase === 'thinking' || state.shown >= state.text.length) {
        return { ...state, done: true, shown: state.text.length, phase: 'settled' }
      }
      return { ...state, done: true }
    case 'stopped':
      return { ...state, done: true, shown: state.text.length, phase: 'settled' }
    case 'error':
      return {
        ...state,
        phase: 'failed',
        error: { message: event.error || 'Request failed', status: event.status ?? null, busy: event.status === 409 },
      }
    default:
      return state
  }
}

// What the progress line says while Babette works: the newest trace step.
export function traceLine(trace) {
  if (!Array.isArray(trace) || !trace.length) return ''
  const last = trace[trace.length - 1]
  if (!last || typeof last !== 'object') return ''
  if (last.kind === 'thinking') return 'thinking…'
  const label = last.label || last.name || last.tool || last.kind || ''
  return typeof label === 'string' ? label : ''
}
