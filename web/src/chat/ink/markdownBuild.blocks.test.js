/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from 'vitest'
import { createInkBuilder } from './markdownBuild.js'
import { renderChatMarkdown } from '../markdown.js'

// The text each block holds, in order. A letter in the wrong paragraph passes a
// flat letter-order check and fails this one.
const BLOCKS = 'P,LI,H1,H2,H3,BLOCKQUOTE'.split(',')
function blockTexts(root) {
  const out = []
  function walk(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return
    if (BLOCKS.includes(node.tagName)) out.push(node.tagName + ':' + node.textContent.replace(/\s+/g, ' ').trim())
    for (const child of node.children) walk(child)
  }
  walk(root)
  return out
}

// Babette's own sentences from the 2026-10-20 screenshot, where the first letter
// after a paragraph break (T of Tune, I of I only) sat at the end of the one above.
const REPLY =
  'Ah — *seeping ink*! My words arrive the way a recipe soaks into a card, the way a marinade behaves. 🫖\n\n' +
  "I only hope the effect is behaving itself. The right pace is a good braise — you can feel it taking its time and know the time is doing something.\n\n" +
  'Tune it gently, chère maison. And if the ink ever behaves badly, blame the pen, never the hand.\n\n' +
  '- **One** thing\n' +
  '- Another thing\n\n' +
  'Bonne soirée!'

const rendered = (src) => {
  const el = document.createElement('div')
  el.innerHTML = renderChatMarkdown(src)
  return blockTexts(el)
}

describe('streamed ink keeps every letter in its own block', () => {
  for (const step of [1, 2, 3, 5, 7, 12]) {
    it(`reveal ${step} letter(s) at a time`, () => {
      // Several starting offsets, so a chunk edge falls on every spot in the text.
      for (let start = 0; start < step; start++) {
        const host = document.createElement('div')
        const builder = createInkBuilder(host)
        let at = start
        while (at < REPLY.length) {
          at = Math.min(REPLY.length, at + step)
          builder.setTyped(REPLY.slice(0, at))
          // At every step the live blocks are what a fresh render of the same
          // prefix gives (a half emoji at the edge is held back, not shown).
          const shown = REPLY.slice(0, at).replace(/[\ud800-\udbff]$/, '')
          expect(blockTexts(host), `step ${step} start ${start} after ...${JSON.stringify(shown.slice(-22))}`).toEqual(rendered(shown))
        }
      }
    })
  }
})
