import { describe, expect, it } from 'vitest'
import { handIsPlain, seepMs } from './ink/constants.js'
import { advance, BASE_CPS, LAG_MS } from './reveal.js'
import { readNdjson } from './stream.js'
import { initialTurn, traceLine, turnReducer } from './turn.js'

const run = (state, ...actions) => actions.reduce(turnReducer, state)
const ev = (event) => ({ type: 'event', event })
const sending = () => run(initialTurn, { type: 'type', draft: 'hi' }, { type: 'send', text: 'hi', submissionId: 's1' })
// Drain the reveal with 16 ms frames. Pace comes from the stream, not a slider.
function drain(state) {
  for (let i = 0; i < 100000 && state.phase === 'revealing'; i++) {
    state = turnReducer(state, { type: 'tick', dt: 16, band: 45 })
  }
  return state
}

// Study arrivals: uneven bursts, no punctuation delay of their own.
function arrivals(total, rng) {
  const out = []
  let t = 700
  let n = 0
  while (n < total) {
    n = Math.min(total, n + 8 + Math.floor(rng() * 60))
    out.push({ at: t, upto: n })
    t += 60 + rng() * (rng() < 0.15 ? 900 : 260)
  }
  return out
}

function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
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
  it('a long frame still lights only a few letters', () => {
    const dumped = advance(0, 2000, 100, 2000)
    expect(Math.floor(dumped.shown)).toBeLessThanOrEqual(4)
    expect(dumped.shown).toBeGreaterThan(0)
  })
  it('eases toward a burst instead of stepping to the catch-up pace', () => {
    const target = 2000 / (LAG_MS / 1000)
    const { paces } = frames(2000, 160)
    expect(paces[0]).toBeGreaterThan(BASE_CPS)
    expect(paces[0]).toBeLessThan(target * 0.5)
    expect(paces[paces.length - 1]).toBeGreaterThan(paces[0])
    for (let i = 1; i < paces.length; i++) expect(paces[i]).toBeGreaterThanOrEqual(paces[i - 1] - 1e-9)
  })
  it('does not slow while a lag-window of text is still waiting', () => {
    let shown = 0
    let cps = BASE_CPS
    let prev = cps
    for (let t = 0; t < LAG_MS - 100 && 2000 - shown > BASE_CPS * (LAG_MS / 1000); t += 16) {
      const next = advance(shown, 2000, 16, cps)
      expect(next.cps).toBeGreaterThanOrEqual(prev - 1e-9)
      prev = next.cps
      shown = next.shown
      cps = next.cps
    }
  })
  it('drops back to the base pace once caught up', () => {
    expect(frames(80, 3000).cps).toBe(BASE_CPS)
    expect(frames(80, 3000).shown).toBe(80)
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
    const s = run(sending(), ev({ type: 'delta', text: 'wrong' }), { type: 'tick', dt: 16, band: 45 }, ev({ type: 'reset' }))
    expect(s).toMatchObject({ text: '', shown: 0, phase: 'revealing' })
  })

  it('the reveal follows the stream and settles when caught up', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Hi.' }), ev({ type: 'done' }))
    expect(s.phase).toBe('revealing')
    s = turnReducer(s, { type: 'tick', dt: 16, band: 45 })
    expect(s.shown).toBeGreaterThan(0)
    expect(s.shown).toBeLessThan(3)
    s = drain(s)
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe(3)
  })
  it('adds no pause after punctuation', () => {
    const text = 'Hi. There, friend;'
    const at = []
    let shown = 0
    let cps = BASE_CPS
    let t = 0
    while (shown < text.length && t < 20000) {
      const next = advance(shown, text.length, 16, cps)
      t += 16
      shown = next.shown
      cps = next.cps
      while (at.length < Math.floor(shown)) at.push(t)
    }
    const gaps = at.slice(1).map((stamp, i) => stamp - at[i])
    expect(Math.max(...gaps)).toBeLessThan(50)
    const period = text.indexOf('.')
    const comma = text.indexOf(',')
    expect(at[period + 1] - at[period]).toBeLessThan(50)
    expect(at[comma + 1] - at[comma]).toBeLessThan(50)
  })
  it('keeps a burst from lighting as a block', () => {
    const total = 1412
    const plan = arrivals(total, mulberry32(19))
    let shown = 0
    let cps = BASE_CPS
    let prev = 0
    let maxLit = 0
    const lastAt = plan[plan.length - 1].at
    for (let t = 0; t <= lastAt + LAG_MS + 400; t += 16) {
      const received = plan.filter((a) => a.at <= t).reduce((m, a) => Math.max(m, a.upto), 0)
      const next = advance(shown, received, 16, cps)
      maxLit = Math.max(maxLit, Math.floor(next.shown) - prev)
      prev = Math.floor(next.shown)
      shown = next.shown
      cps = next.cps
    }
    expect(shown).toBe(total)
    expect(maxLit).toBeLessThanOrEqual(6)
  })
  it('band 0 is plain and the seep is the band divided by the pace', () => {
    expect(handIsPlain(0, false)).toBe(true)
    expect(handIsPlain(45, false)).toBe(false)
    expect(handIsPlain(45, true)).toBe(true)
    expect(seepMs(160, 45)).toBe(281)
    expect(seepMs(160, 0)).toBe(0)
    expect(seepMs(80, 20)).toBe(250)
    let s = run(sending(), ev({ type: 'delta', text: 'Plain words.' }), ev({ type: 'done' }))
    s = turnReducer(s, { type: 'tick', dt: 16, band: 0 })
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe('Plain words.'.length)
  })

  it('reduced motion shows the whole buffer at once', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Plain.' }), ev({ type: 'done' }))
    s = turnReducer(s, { type: 'tick', instant: true })
    expect(s.phase).toBe('settled')
    expect(s.shown).toBe(6)
  })
  it('a tick that moves nothing returns the same state', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Hi.' }))
    const waiting = turnReducer(s, { type: 'tick', dt: 0, band: 45 })
    expect(waiting).toBe(s)
    const instant = turnReducer(s, { type: 'tick', instant: true })
    const instantAgain = turnReducer(instant, { type: 'tick', instant: true })
    expect(instant.shown).toBe(3)
    expect(instant.phase).toBe('revealing')
    expect(instantAgain).toBe(instant)
  })
  it('a tick once the reveal has caught the buffer returns the same state', () => {
    let s = run(sending(), ev({ type: 'delta', text: 'Hi.' }))
    for (let i = 0; i < 80 && s.shown < s.text.length; i++) {
      s = turnReducer(s, { type: 'tick', dt: 16, band: 45 })
    }
    expect(s.phase).toBe('revealing')
    expect(s.shown).toBe(s.text.length)
    const parked = turnReducer(s, { type: 'tick', dt: 16, band: 45 })
    expect(parked).toBe(s)
    expect(parked.cps).toBe(BASE_CPS)
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
  it('links a card on its title, without showing the id', () => {
    const html = renderChatMarkdown('Make [Zuni Chicken](CBK-1408) tonight.')
    expect(html).toContain('data-recipe="CBK-1408"')
    expect(html).toContain('href="/recipes/CBK-1408"')
    expect(html).toContain('>Zuni Chicken</a>')
    expect(html).not.toContain('>CBK-1408<')
    expect(html).not.toContain('target="_blank"')
  })
  it('refuses unsafe links', () => {
    expect(renderChatMarkdown('[x](javascript:alert(1))')).not.toContain('href="javascript')
  })
  it('links an id after a link and leaves the id inside the link as its text', () => {
    const html = renderChatMarkdown('See [CBK-0001](/recipes/CBK-0001) then CBK-0002.')
    expect(html.match(/data-recipe="CBK-0001"/g)).toHaveLength(1)
    expect(html).toContain('data-recipe="CBK-0002"')
    expect(html).not.toContain('data-recipe="CBK-0001">CBK-0001</a></a>')
  })
})
