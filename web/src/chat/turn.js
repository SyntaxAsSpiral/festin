// Chat Turn machine (state-machine.md §2.4, §8.4 Turn). Pure: no fetch, no timers.
import { handIsPlain } from './ink/constants.js'
import { BASE_CPS, advance } from './reveal.js'

export const initialTurn = {
  phase: 'idle', // idle | composing | thinking | revealing | settled | failed
  draft: '',
  sent: null, // { text, photos, files, submissionId } of the message in flight, kept for retry
  requestId: null,
  text: '', // reply received so far
  shown: 0, // fractional characters revealed; render Math.floor(shown)
  cps: BASE_CPS, // pace carried between frames
  done: false, // server said done; settle when the buffer drains
  trace: null,
  error: null,
  attempt: 0, // bumps on each send and retry; the network follows it
}

function afterReply(state) {
  return state.draft.trim() ? 'composing' : 'idle'
}

function clearReveal(extra = {}) {
  return { text: '', shown: 0, cps: BASE_CPS, done: false, trace: null, requestId: null, ...extra }
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
      // Reduced motion and wet band 0: the whole buffer at once, plain text.
      if (action.instant || handIsPlain(action.band)) {
        const shown = state.text.length
        if (state.done) {
          if (state.shown === shown && state.phase === 'settled') return state
          return { ...state, shown, cps: BASE_CPS, phase: 'settled' }
        }
        if (state.shown === shown && state.cps === BASE_CPS) return state
        return { ...state, shown, cps: BASE_CPS }
      }
      // The frame loop passes the position it already revealed. Tests omit it
      // and the machine advances one frame itself.
      const next = Number.isFinite(action.shown)
        ? { shown: Math.min(state.text.length, Math.max(0, action.shown)), cps: action.cps ?? state.cps }
        : advance(state.shown, state.text.length, action.dt ?? 16, state.cps)
      if (state.done && next.shown >= state.text.length) {
        if (state.shown === state.text.length && state.cps === BASE_CPS) {
          return { ...state, phase: 'settled' }
        }
        return { ...state, shown: state.text.length, cps: BASE_CPS, phase: 'settled' }
      }
      // Parked on the buffer: keep this object so a waiting frame does not
      // re-render the page under the chat.
      if (next.shown === state.shown && next.cps === state.cps) return state
      return { ...state, shown: next.shown, cps: next.cps }
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
      return { ...state, text: '', shown: 0, cps: BASE_CPS }
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
