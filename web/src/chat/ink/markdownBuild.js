import { MASK_SIZE_EM } from './constants.js'
import { renderChatMarkdown } from '../markdown.js'

const FLOW = new Set(['P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH', 'PRE', 'BLOCKQUOTE'])
const PHRASE = new Set(['STRONG', 'EM', 'A', 'CODE', 'SPAN', 'DEL', 'S', 'I', 'B', 'U'])
// Characters that may reshape Markdown; a delta containing these forces a remount.
const STRUCT = /[\n*`_\[\]#>|!~\\]/

function inTextContext(tagName) {
  return FLOW.has(tagName) || PHRASE.has(tagName)
}

function randomOffset() {
  return (Math.random() * MASK_SIZE_EM).toFixed(2) + 'em'
}

function makeSpan(ch) {
  const s = document.createElement('span')
  s.className = 'ink-c'
  s.textContent = ch
  s.style.setProperty('--mx', randomOffset())
  s.style.setProperty('--my', randomOffset())
  return s
}

// Walk a rendered Markdown tree; skip inter-element whitespace so span
// indices match visible characters only.
function collectChars(root) {
  const chars = []
  function walk(node, inText) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!inText) return
      for (const ch of node.textContent) chars.push(ch)
      return
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const next = inText || inTextContext(node.tagName)
      for (const child of node.childNodes) walk(child, next)
    }
  }
  for (const child of root.childNodes) walk(child, false)
  return chars
}

function cloneShell(node, takeChar, inText) {
  if (node.nodeType === Node.TEXT_NODE) {
    if (!inText) return null
    const frag = document.createDocumentFragment()
    for (let i = 0; i < node.textContent.length; i++) {
      const span = takeChar()
      if (span) frag.append(span)
    }
    return frag
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return null
  const el = document.createElement(node.tagName.toLowerCase())
  for (const attr of node.attributes) el.setAttribute(attr.name, attr.value)
  const next = inText || inTextContext(node.tagName)
  for (const child of [...node.childNodes]) {
    const built = cloneShell(child, takeChar, next)
    if (built) el.append(built)
  }
  return el
}

function lastInkParent(host) {
  const all = host.querySelectorAll('.ink-c')
  if (!all.length) return null
  return all[all.length - 1].parentNode
}

export function createInkBuilder(host) {
  const spans = []
  let lastSrc = ''

  function ensureSpans(count, textChars) {
    while (spans.length < count) {
      const i = spans.length
      spans.push(makeSpan(textChars[i]))
    }
    if (spans.length > count) {
      for (let i = count; i < spans.length; i++) spans[i].remove()
      spans.length = count
    }
    for (let i = 0; i < count; i++) {
      if (spans[i].textContent !== textChars[i]) spans[i].textContent = textChars[i]
    }
  }

  function remount(markdownRoot) {
    let idx = 0
    const takeChar = () => spans[idx++]
    const kids = [...markdownRoot.childNodes]
      .map((n) => cloneShell(n, takeChar, false))
      .filter(Boolean)
    host.replaceChildren(...kids)
  }

  function fullRebuild(src) {
    if (!src) {
      spans.length = 0
      lastSrc = ''
      host.replaceChildren()
      return
    }
    const wrap = document.createElement('div')
    wrap.innerHTML = renderChatMarkdown(src)
    const textChars = collectChars(wrap)
    ensureSpans(textChars.length, textChars)
    remount(wrap)
    lastSrc = src
  }

  function tryAppend(src) {
    if (!lastSrc || !src.startsWith(lastSrc) || src.length <= lastSrc.length) return false
    const delta = src.slice(lastSrc.length)
    if (STRUCT.test(delta)) return false
    const parent = lastInkParent(host)
    if (!parent) return false
    // Plain growth: each source char is one visible char (no markers).
    for (const ch of delta) {
      const s = makeSpan(ch)
      spans.push(s)
      parent.append(s)
    }
    lastSrc = src
    return true
  }

  return {
    get length() {
      return spans.length
    },
    get spans() {
      return spans
    },
    setTyped(text) {
      const src = String(text || '')
      if (src === lastSrc) return
      if (src.length < lastSrc.length || !src.startsWith(lastSrc.slice(0, Math.min(lastSrc.length, src.length)))) {
        fullRebuild(src)
        return
      }
      if (tryAppend(src)) return
      fullRebuild(src)
    },
    light(index, { durationMs, mx, my } = {}) {
      const el = spans[index]
      if (!el) return null
      if (mx != null) el.style.setProperty('--mx', mx)
      if (my != null) el.style.setProperty('--my', my)
      if (durationMs != null) el.style.setProperty('--d', durationMs + 'ms')
      el.classList.add('on')
      return el
    },
    clear() {
      spans.length = 0
      lastSrc = ''
      host.replaceChildren()
    },
  }
}
