import { seepMs as seepMsFor } from './constants.js'
import { createInkBuilder } from './markdownBuild.js'
import { ensureSeepStyles } from './seep.js'

// Owns the live reply DOM outside React: typed Markdown structure with per-letter
// spans. React keeps an empty host; this module appends into it so re-renders
// do not restart letter animations.
export function mountInkLayer(host, { plain = false } = {}) {
  if (!host) return { sync() {}, reset() {}, destroy() {} }
  const builder = createInkBuilder(host)
  let lit = 0
  let destroyed = false
  let lastSync = 0

  if (plain) host.classList.add('ink-plain')
  else host.classList.remove('ink-plain')

  void ensureSeepStyles()

  return {
    sync(sourceText, shown, { cps, plain: nextPlain } = {}) {
      if (destroyed) return
      if (nextPlain != null) {
        host.classList.toggle('ink-plain', Boolean(nextPlain))
      }
      const text = String(sourceText || '')
      const n = Math.max(0, Math.min(Math.floor(shown), text.length))
      if (n < lit) {
        builder.clear()
        lit = 0
      }
      const prefix = text.slice(0, n)
      builder.setTyped(prefix)
      const duration = seepMsFor(cps)
      // Letters due in the same frame would all start together and the front would
      // advance in clumps (visible at high speed). Spread each batch back across
      // the time since the last frame, so every letter starts at its own moment.
      const now = performance.now()
      const elapsed = Math.min(Math.max(0, now - (lastSync || now)), 100)
      lastSync = now
      const fresh = []
      for (let i = 0; i < builder.length; i++) {
        if (!builder.spans[i].classList.contains('on')) fresh.push(i)
      }
      fresh.forEach((i, j) => {
        const lateMs = fresh.length > 1 ? (elapsed * (fresh.length - 1 - j)) / fresh.length : 0
        builder.light(i, { durationMs: duration, lateMs })
      })
      lit = n
    },
    reset() {
      lit = 0
      builder.clear()
    },
    destroy() {
      destroyed = true
      builder.clear()
    },
  }
}
