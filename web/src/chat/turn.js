// Chat Turn machine (state-machine.md §2.4, §8.4 Turn). Pure: no fetch, no timers.
import { advance } from './reveal.js'

export const initialTurn = {
  phase: 'idle', // idle | composing | thinking | revealing | settled | failed
  draft: '',
  sent: null, // { text, photos, submissionId } of the message in flight, kept for retry
  requestId: null,
  text: '', // reply received so far
  shown: 0, // characters revealed (fractional)
  cps: 0, // reveal pace carried between frames
  done: false, // server said done; settle when the buffer drains
  trace: null,
  error: null,
  attempt: 0, // bumps on each send and retry; the network follows it
}

function afterReply(state) {
  return state.draft.trim() ? 'composing' : 'idle'
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
        sent: { text: action.text, photos: action.photos || [], submissionId: action.submissionId },
      }
    }
    case 'retry': {
      if (state.phase !== 'failed' || !state.sent) return state
      return { ...state, phase: 'thinking', attempt: state.attempt + 1, error: null, text: '', shown: 0, done: false, trace: null, requestId: null }
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
      const { shown, cps } = advance(state.shown, state.text.length, action.dt, state.cps)
      if (state.done && shown >= state.text.length) return { ...state, shown, cps, phase: 'settled' }
      return { ...state, shown, cps }
    }
    case 'absorbed': {
      // The settled reply is now in the reloaded transcript.
      if (state.phase !== 'settled') return state
      return { ...state, phase: afterReply(state), sent: null, text: '', shown: 0, done: false, trace: null, requestId: null }
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
      return { ...state, text: '', shown: 0 }
    case 'trace':
      return { ...state, trace: event.trace ?? null }
    case 'done':
      if (state.phase === 'thinking' || state.shown >= state.text.length) return { ...state, done: true, shown: state.text.length, phase: 'settled' }
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
