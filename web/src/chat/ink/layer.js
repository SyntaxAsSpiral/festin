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
      for (let i = 0; i < builder.length; i++) {
        if (!builder.spans[i].classList.contains('on')) {
          builder.light(i, { durationMs: duration })
        }
      }
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
