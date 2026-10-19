import { describe, expect, it } from 'vitest'
import { advance, BASE_CPS, LAG_MS } from './reveal.js'
import { readNdjson } from './stream.js'
import { initialTurn, traceLine, turnReducer } from './turn.js'

const run = (state, ...actions) => actions.reduce(turnReducer, state)
const ev = (event) => ({ type: 'event', event })
const sending = () => run(initialTurn, { type: 'type', draft: 'hi' }, { type: 'send', text: 'hi', submissionId: 's1' })
// Drain the ghost typist with 16 ms frames at a fixed writing speed.
function drain(state, cps = 55) {
  let now = 1
  for (let i = 0; i < 100000 && state.phase === 'revealing'; i++) {
    state = turnReducer(state, { type: 'tick', now, cps, rng: () => 0.5 })
    now += 16
  }
  return state
}

describe('reveal pacing', () => {
  const frames = (total, ms, start = { shown: 0, cps: 0 }) => {
    let s = start
    const paces = []
    for (let t = 0; t < ms; t += 16) {
      s = advance(s.shown, total, 16, s.cps)
      paces.push(s.cps)
    }
    return { ...s, paces }
  }
  it('shows a short reply at the base pace', () => {
    expect(advance(0, 10, 16).shown).toBeCloseTo((BASE_CPS * 16) / 1000)
  })
  it('clears a big burst within the lag window', () => {
    expect(frames(2000, LAG_MS + 50).shown).toBe(2000)
  })
  it('holds its pace through a catch-up instead of slowing', () => {
    const { paces } = frames(2000, LAG_MS - 100)
    expect(Math.min(...paces)).toBe(Math.max(...paces))
  })
  it('drops back to the base pace once caught up', () => {
    expect(frames(2000, LAG_MS + 50).cps).toBe(BASE_CPS)
  })
  it('never overshoots, and caps a long background frame', () => {
    expect(advance(5, 6, 1000).shown).toBe(6)
    expect(advance(0, 1e5, 60000).shown).toBe(advance(0, 1e5, 100).shown)
  })
})

describe('turn machine', () => {
  it('typing moves idle to composing and back', () => {
    const s = run(initialTurn, { type: 'type', draft: 'a' })
    expect(s.phase).toBe('composing')
    expect(run(s, { type: 'type', draft: '  ' }).phase).toBe('idle')
  })
  it('send clears the draft, keeps the message, and bumps the attempt', () => {
    const s = sending()
    expect(s).toMatchObject({ phase: 'thinking', draft: '', attempt: 1, sent: { text: 'hi', submissionId: 's1' } })
  })
  it('start and trace keep thinking without a new attempt', () => {
    const s = run(sending(), ev({ type: 'start', request_id: 'r1' }), ev({ type: 'trace', trace: [{ kind: 'tool', label: 'Looked in the cookbook' }] }))
    expect(s).toMatchObject({ phase: 'thinking', requestId: 'r1', attempt: 1 })
  })
  it('the first delta starts revealing; done waits for the buffer to drain', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Leek and ' }), ev({ type: 'delta', text: 'gruyère.' }), ev({ type: 'done' }))
    expect(s.phase).toBe('revealing')
    expect(s.done).toBe(true)
    s = drain(s)
    expect(s.phase).toBe('settled')
    expect(Math.floor(s.shown)).toBe('Leek and gruyère.'.length)
  })
  it('reset clears what was received and shown', () => {
    const s = run(sending(), ev({ type: 'delta', text: 'wrong' }), { type: 'tick', now: 20, cps: 55, rng: () => 0.5 }, ev({ type: 'reset' }))
    expect(s).toMatchObject({ text: '', shown: 0, phase: 'revealing' })
  })

  it('the ghost typist paces the reveal and settles when caught up', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Hi.' }), ev({ type: 'done' }))
    expect(s.phase).toBe('revealing')
    s = turnReducer(s, { type: 'tick', now: 10, cps: 55, rng: () => 0.5 })
    expect(s.shown).toBe(1)
    s = drain(s)
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe(3)
  })

  it('reduced motion shows the whole buffer at once', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Plain.' }), ev({ type: 'done' }))
    s = turnReducer(s, { type: 'tick', instant: true })
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe(6)
  })
  it('stopped settles at once with what arrived', () => {
    const s = run(sending(), ev({ type: 'delta', text: 'half a reply' }), ev({ type: 'stopped' }))
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe('half a reply'.length)
  })
  it('stopped before any text settles from thinking', () => {
    expect(run(sending(), ev({ type: 'stopped' })).phase).toBe('settled')
  })
  it('a 409 fails as busy; retry goes back to thinking with a new attempt and the same message', () => {
    let s = run(sending(), ev({ type: 'error', status: 409, error: 'Babette is still answering.' }))
    expect(s.phase).toBe('failed')
    expect(s.error.busy).toBe(true)
    s = run(s, { type: 'retry' })
    expect(s).toMatchObject({ phase: 'thinking', attempt: 2, sent: { submissionId: 's1' }, error: null })
  })
  it('dismiss puts the unsent text back in the composer and keeps the attempt count', () => {
    const s = run(sending(), ev({ type: 'error', error: 'x' }), { type: 'dismiss' })
    expect(s).toMatchObject({ phase: 'composing', draft: 'hi', attempt: 1 })
    expect(run(s, { type: 'send', text: 'hi', submissionId: 's2' }).attempt).toBe(2)
  })
  it('events after the turn ended are ignored', () => {
    const s = run(sending(), ev({ type: 'stopped' }), ev({ type: 'delta', text: 'late' }))
    expect(s.text).toBe('')
  })
  it('absorbed hands a settled reply over to the transcript', () => {
    const s = run(sending(), ev({ type: 'stopped' }), { type: 'absorbed' })
    expect(s).toMatchObject({ phase: 'idle', sent: null, text: '' })
  })
  it('a draft typed while Babette answers survives and makes the next phase composing', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'ok' }), { type: 'type', draft: 'next' })
    expect(s.phase).toBe('revealing')
    s = run(drain(run(s, ev({ type: 'done' }))), { type: 'absorbed' })
    expect(s).toMatchObject({ phase: 'composing', draft: 'next' })
  })
})

describe('trace line', () => {
  it('names the newest tool step, or says thinking', () => {
    expect(traceLine([{ kind: 'thinking', text: '…' }, { kind: 'tool', name: 'search_cookbook', label: 'Looked in the cookbook' }])).toBe('Looked in the cookbook')
    expect(traceLine([{ kind: 'thinking', text: 'hmm' }])).toBe('thinking…')
    expect(traceLine(null)).toBe('')
  })
})

describe('NDJSON reader', () => {
  it('joins lines split across chunks and skips junk', async () => {
    const chunks = ['{"type":"start","request_id":"r"}\n{"type":"del', 'ta","text":"hi"}\n\nnot json\n{"type":"done"}']
    const enc = new TextEncoder()
    let i = 0
    const reader = { read: async () => (i < chunks.length ? { value: enc.encode(chunks[i++]), done: false } : { value: undefined, done: true }) }
    const seen = []
    await readNdjson(reader, (e) => seen.push(e.type))
    expect(seen).toEqual(['start', 'delta', 'done'])
  })
})

describe('chat markdown', async () => {
  const { renderChatMarkdown } = await import('./markdown.js')
  it('renders lists and bold, drops raw HTML', () => {
    const html = renderChatMarkdown('- **Leeks** first\n- then <b>x</b>')
    expect(html).toContain('<strong>Leeks</strong>')
    expect(html).toContain('<li>')
    expect(html).not.toContain('<b>')
  })
  it('links recipe ids, but not inside code or links', () => {
    expect(renderChatMarkdown('Try CBK-0012.')).toContain('data-recipe="CBK-0012"')
    expect(renderChatMarkdown('`CBK-0012`')).not.toContain('data-recipe')
    expect(renderChatMarkdown('[see CBK-0012](/x)')).not.toContain('data-recipe')
  })
  it('refuses unsafe links', () => {
    expect(renderChatMarkdown('[x](javascript:alert(1))')).not.toContain('href="javascript')
  })
})
