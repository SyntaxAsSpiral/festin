/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from 'vitest'
import { createInkBuilder } from './markdownBuild.js'
import { renderChatMarkdown } from '../markdown.js'

// However a reply is chunked on the way in, the live tree ends with the same
// structure and text as the settled Markdown it hands over to.
const REPLIES = [
  "Don't throw it out. A *split* sauce is only fat that has let go of the flour.\n\n" +
    '1. Pull the pan **off the heat** and let it calm.\n' +
    '2. Whisk in a spoonful of *just-boiled* water, until it turns glossy.\n' +
    '3. If it fights you, a *fluffy* knob of cold butter finishes the job.\n\n' +
    'Next time, try [Pan Gravy](CBK-0042): judge the *fond* by its colour.',
  'Voilà, the whole shelf — a crowded room:\n\n' +
    '**The shape of the box**\n' +
    '- **12 cards** in all — 10 formules, 2 praxis.\n' +
    '- Mostly from **[The Old Box](CBK-0001) — 9 cards** — and a few of mine.\n\n' +
    '**Techniques** — the quiet backbone:\n' +
    '[Beans](CBK-0002), [Stock](CBK-0003), [Fond](CBK-0004).\n\n' +
    '> A note in the margin.\n\n' +
    '## Next\n' +
    'Shall I read a shelf in full? 🫖',
]

function shape(root) {
  const out = []
  function walk(node) {
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.classList.contains('ink-c')) return
      out.push(node.tagName + (node.getAttribute('href') ? '@' + node.getAttribute('href') : ''))
    }
    for (const child of node.childNodes) walk(child)
  }
  for (const child of root.childNodes) walk(child)
  return out
}

// The letters in order. Whitespace between block tags differs between the two
// trees and is not ink; the tag shape above catches structure.
const visible = (el) => el.textContent.replace(/\s+/g, '')

function seeded(seed) {
  let s = seed
  return () => (s = (s * 16807) % 2147483647) / 2147483647
}

describe('streamed ink ends as the settled Markdown', () => {
  for (const [n, reply] of REPLIES.entries()) {
    for (const seed of [1, 7, 42, 99]) {
      it(`reply ${n + 1}, chunking ${seed}`, () => {
        const host = document.createElement('div')
        const builder = createInkBuilder(host)
        const rnd = seeded(seed)
        let at = 0
        while (at < reply.length) {
          at = Math.min(reply.length, at + 1 + Math.floor(rnd() * 12))
          builder.setTyped(reply.slice(0, at))
        }
        const settled = document.createElement('div')
        settled.innerHTML = renderChatMarkdown(reply)
        expect(shape(host)).toEqual(shape(settled))
        expect(visible(host)).toBe(visible(settled))
      })
    }
  }
})
