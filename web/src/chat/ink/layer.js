import { DEFAULT_WET_BAND, seepMs as seepMsFor } from './constants.js'
import { createInkBuilder } from './markdownBuild.js'
import { planWordSeep, readGrain } from './grain.js'
import { ensureSeepStyles, seepReady } from './seep.js'

// Owns the live reply DOM outside React: typed Markdown structure with per-letter
// spans. React keeps an empty host; this module appends into it so re-renders
// do not restart letter animations.
// The first letter of the word letter i belongs to: the run of letters before it
// that are not blank and sit on the same line.
function wordStart(spans, i) {
  const top = spans[i].offsetTop
  let s = i
  while (s > 0 && i - s < 24 && /\S/.test(spans[s - 1].textContent) && Math.abs(spans[s - 1].offsetTop - top) < 3) s--
  return s
}

export function mountInkLayer(host, { plain = false } = {}) {
  if (!host) return { sync() {}, reset() {}, destroy() {} }
  const builder = createInkBuilder(host)
  const grain = readGrain()
  let lit = 0
  let litSpans = 0
  let destroyed = false
  let lastSync = 0

  if (plain) host.classList.add('ink-plain')
  else host.classList.remove('ink-plain')

  void ensureSeepStyles()
  // A finished seep is just sepia text. Leaving the animation attached makes
  // every later frame restyle the whole reply.
  host.addEventListener('animationend', (event) => {
    if (event.animationName !== 'ink-seep-dry') return
    const el = event.target
    if (!el.classList || !el.classList.contains('ink-c')) return
    el.style.animation = 'none'
    el.style.color = 'var(--bb-sepia, #7a5a3a)'
    el.style.maskImage = 'none'
    el.style.webkitMaskImage = 'none'
  })

  return {
    sync(sourceText, shown, { cps, band, plain: nextPlain } = {}) {
      if (destroyed) return
      if (nextPlain != null) {
        host.classList.toggle('ink-plain', Boolean(nextPlain))
      }
      const text = String(sourceText || '')
      const n = Math.max(0, Math.min(Math.floor(shown), text.length))
      if (n < lit) {
        builder.clear()
        lit = 0
        litSpans = 0
      }
      const prefix = text.slice(0, n)
      builder.setTyped(prefix)
      // Letters wait, hidden, until the masks exist; lit earlier they would show
      // plain and then restart masked. The next sync lights what has piled up.
      if (!seepReady()) return
      const duration = seepMsFor(cps, band ?? DEFAULT_WET_BAND)
      // Letters due in the same frame would all start together and the front would
      // advance in clumps (visible at high speed). Spread each batch back across
      // the time since the last frame, so every letter starts at its own moment.
      const now = performance.now()
      const elapsed = Math.min(Math.max(0, now - (lastSync || now)), 100)
      lastSync = now
      if (builder.length < litSpans) litSpans = 0
      const fresh = []
      for (let i = litSpans; i < builder.length; i++) {
        if (!builder.spans[i].classList.contains('on')) fresh.push(i)
      }
      if (grain === 'word' && fresh.length) {
        const { spans } = builder
        const plan = planWordSeep({
          fresh,
          elapsed,
          startOf: (i) => wordStart(spans, i),
          offsetOf: (i, s) => spans[i].offsetLeft - spans[s].offsetLeft,
          baseOf: (s) => (spans[s].dataset.wbx ? { x: Number(spans[s].dataset.wbx), y: Number(spans[s].dataset.wby) } : null),
        })
        for (const { index, start, base, lateMs, mx, my } of plan) {
          spans[start].dataset.wbx = String(base.x)
          spans[start].dataset.wby = String(base.y)
          builder.light(index, { durationMs: duration, lateMs, mx, my })
        }
      } else {
        fresh.forEach((i, j) => {
          const lateMs = fresh.length > 1 ? (elapsed * (fresh.length - 1 - j)) / fresh.length : 0
          builder.light(i, { durationMs: duration, lateMs })
        })
      }
      lit = n
      litSpans = builder.length
    },
    reset() {
      lit = 0
      litSpans = 0
      builder.clear()
    },
    destroy() {
      destroyed = true
      builder.clear()
    },
  }
}
