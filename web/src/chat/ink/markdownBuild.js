import { MASK_SIZE_EM } from './constants.js'
import { renderChatMarkdown } from '../markdown.js'

const FLOW = new Set(['P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH', 'PRE', 'BLOCKQUOTE'])
const PHRASE = new Set(['STRONG', 'EM', 'A', 'CODE', 'SPAN', 'DEL', 'S', 'I', 'B', 'U'])
// Characters that may reshape Markdown. Plain growth can append spans; anything
// else rebuilds only the units that changed (the last line, the last list item).
const STRUCT = /[\n*`_\[\]()#>|!~\\]/

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

// markdown-it writes a newline after <br>. It is not a character of the reply.
function isBreakGap(node) {
  if (!node || node.nodeType !== Node.TEXT_NODE) return false
  if (node.textContent.trim() !== '') return false
  const prev = node.previousSibling
  const next = node.nextSibling
  return Boolean((prev && prev.nodeName === 'BR') || (next && next.nodeName === 'BR'))
}

function walkChars(node, inText, chars) {
  if (node.nodeType === Node.TEXT_NODE) {
    if (!inText || isBreakGap(node)) return
    for (const ch of node.textContent) chars.push(ch)
    return
  }
  if (node.nodeType === Node.ELEMENT_NODE) {
    const next = inText || inTextContext(node.tagName)
    for (const child of node.childNodes) walkChars(child, next, chars)
  }
}

function collectChars(root) {
  const chars = []
  for (const child of root.childNodes) walkChars(child, false, chars)
  return chars
}

function charsIn(el) {
  const chars = []
  walkChars(el, false, chars)
  return chars
}

function cloneShell(node, takeChar, inText) {
  if (node.nodeType === Node.TEXT_NODE) {
    if (!inText || isBreakGap(node)) return null
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

// Same shape from a markdown tree and from the live tree, where letters are spans.
function signature(el) {
  function walk(node, inText) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!inText || isBreakGap(node)) return ''
      return node.textContent
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return ''
    if (node.classList && node.classList.contains('ink-c')) return node.textContent
    const next = inText || inTextContext(node.tagName)
    const attrs = []
    for (const attr of node.attributes) {
      if (attr.name === 'style') continue
      attrs.push(`${attr.name}="${attr.value}"`)
    }
    attrs.sort()
    let inner = ''
    for (const child of node.childNodes) inner += walk(child, next)
    const open = attrs.length ? `<${node.tagName} ${attrs.join(' ')}>` : `<${node.tagName}>`
    return open + inner + `</${node.tagName}>`
  }
  return walk(el, false)
}

// A list is one unit per item, so a new item does not rebuild the ones above it.
function flattenUnits(root) {
  const units = []
  for (const child of root.children) {
    if (child.tagName === 'UL' || child.tagName === 'OL') {
      for (const item of child.children) units.push(item)
    } else {
      units.push(child)
    }
  }
  return units
}

function lastInkParent(host) {
  const all = host.querySelectorAll('.ink-c')
  if (!all.length) return null
  return all[all.length - 1].parentNode
}

export function createInkBuilder(host) {
  const spans = []
  let lastSrc = ''
  let unitSigs = []
  let unitEnds = []
  let unitsDirty = false
  let flowEl = null
  // Source index where the open line starts. Letters never go into an earlier line.
  let flowAt = -1

  function reset() {
    spans.length = 0
    unitSigs = []
    unitEnds = []
    unitsDirty = false
    flowEl = null
    flowAt = -1
    lastSrc = ''
    host.replaceChildren()
  }

  function remember(units, counts) {
    unitSigs = units.map((unit) => signature(unit))
    unitEnds = []
    let end = 0
    for (const count of counts) {
      end += count
      unitEnds.push(end)
    }
    unitsDirty = false
  }

  function ensureTail(start, textChars) {
    const count = start + textChars.length
    while (spans.length < count) spans.push(makeSpan(textChars[spans.length - start]))
    if (spans.length > count) {
      for (let i = count; i < spans.length; i++) spans[i].remove()
      spans.length = count
    }
    for (let i = 0; i < textChars.length; i++) {
      if (spans[start + i].textContent !== textChars[i]) spans[start + i].textContent = textChars[i]
    }
  }

  // Membership is "inside this reply" (host.contains), not "on the page"
  // (isConnected): the builder must behave the same before the host is attached.
  function mountTail(units, spanStart) {
    let idx = spanStart
    const takeChar = () => spans[idx++]
    const live = flattenUnits(host)
    let listEl = null
    if (spanStart > 0 && live.length) {
      const prev = live[live.length - 1]
      if (prev.tagName === 'LI' && host.contains(prev)) listEl = prev.parentNode
    }
    for (const unit of units) {
      const built = cloneShell(unit, takeChar, false)
      if (!built) continue
      if (unit.tagName === 'LI') {
        const want = unit.parentElement
        if (!listEl || !want || listEl.tagName !== want.tagName) {
          listEl = document.createElement((want ? want.tagName : 'UL').toLowerCase())
          if (want) {
            for (const attr of want.attributes) listEl.setAttribute(attr.name, attr.value)
          }
          host.append(listEl)
        }
        listEl.append(built)
      } else {
        listEl = null
        host.append(built)
      }
    }
    const now = performance.now()
    for (let i = spanStart; i < spans.length; i++) {
      const at = Number(spans[i].dataset.at)
      if (at) {
        spans[i].style.animation = ''
        spans[i].style.color = ''
        spans[i].style.maskImage = ''
        spans[i].style.webkitMaskImage = ''
        spans[i].style.animationDelay = `-${Math.round(now - at)}ms`
      }
    }
  }

  function dropTail(keep) {
    const live = flattenUnits(host)
    let listEl = null
    if (keep > 0 && live[keep - 1] && live[keep - 1].tagName === 'LI') listEl = live[keep - 1].parentNode
    for (let i = live.length - 1; i >= keep; i--) {
      const node = live[i]
      const parent = node.parentNode
      node.remove()
      if (parent && parent !== host && (parent.tagName === 'UL' || parent.tagName === 'OL') && parent.childElementCount === 0) {
        if (parent === listEl) listEl = null
        parent.remove()
      }
    }
  }

  function paint(src) {
    const wrap = document.createElement('div')
    wrap.innerHTML = renderChatMarkdown(src)
    if (unitsDirty) {
      const live = flattenUnits(host)
      let end = 0
      const ends = []
      for (const unit of live) {
        end += unit.querySelectorAll('.ink-c').length
        ends.push(end)
      }
      if (end !== spans.length) {
        reset()
        if (src) paint(src)
        return
      }
      unitSigs = live.map((unit) => signature(unit))
      unitEnds = ends
      unitsDirty = false
    }
    const units = flattenUnits(wrap)
    let keep = 0
    const sigs = []
    for (let i = 0; i < units.length; i++) {
      const sig = signature(units[i])
      sigs.push(sig)
      if (keep === i && i < unitSigs.length && sig === unitSigs[i]) keep = i + 1
      else if (keep === i) break
    }
    for (let i = sigs.length; i < units.length; i++) sigs.push(signature(units[i]))
    const spanKeep = keep === 0 ? 0 : unitEnds[keep - 1]
    const counts = []
    const tailChars = []
    for (let i = 0; i < units.length; i++) {
      const chars = charsIn(units[i])
      counts.push(chars.length)
      if (i >= keep) tailChars.push(...chars)
    }
    dropTail(keep)
    ensureTail(spanKeep, tailChars)
    mountTail(units.slice(keep), spanKeep)
    remember(units, counts)
    lastSrc = src
    const live = flattenUnits(host)
    flowEl = live.length ? live[live.length - 1] : null
    flowAt = src.lastIndexOf('\n') + 1
  }

  function openFlow() {
    let node = lastInkParent(host)
    while (node && node !== host && !FLOW.has(node.tagName)) node = node.parentNode
    if (!node || node === host) return null
    return node
  }

  function visibleOf(line) {
    if (!line) return ''
    const wrap = document.createElement('div')
    wrap.innerHTML = renderChatMarkdown(line)
    return collectChars(wrap).join('')
  }

  // Plain letters, and marker characters that are still literal, land on the
  // open line. The line is rebuilt only when Markdown swallows some of them
  // (a bold word or a card link closing).
  function appendToFlow(delta) {
    if (!flowEl || !host.contains(flowEl)) flowEl = openFlow()
    const flow = flowEl
    if (!flow) return false
    for (const ch of delta) {
      const span = makeSpan(ch)
      spans.push(span)
      flow.append(span)
    }
    return true
  }

  function replaceOpenLine(line) {
    if (!flowEl || !host.contains(flowEl)) flowEl = openFlow()
    const flow = flowEl
    if (!flow) return false
    const wrap = document.createElement('div')
    wrap.innerHTML = renderChatMarkdown(line)
    const units = flattenUnits(wrap)
    if (units.length !== 1 || units[0].tagName !== flow.tagName) return false
    // A soft break keeps the earlier lines in this block. Only the open line,
    // the nodes after the last <br>, is replaced.
    const breaks = flow.querySelectorAll('br')
    const lastBr = breaks.length ? breaks[breaks.length - 1] : null
    const owned = []
    for (const span of flow.querySelectorAll('.ink-c')) {
      if (!lastBr || lastBr.compareDocumentPosition(span) & Node.DOCUMENT_POSITION_FOLLOWING) owned.push(span)
    }
    if (!owned.length && charsIn(units[0]).length === 0) return true
    const start = spans.length - owned.length
    if (start < 0 || (owned.length && spans[start] !== owned[0])) return false
    const chars = charsIn(units[0])
    ensureTail(start, chars)
    if (lastBr) {
      let node = lastBr.nextSibling
      while (node) {
        const next = node.nextSibling
        node.remove()
        node = next
      }
    } else {
      flow.replaceChildren()
    }
    let idx = start
    const built = cloneShell(units[0], () => spans[idx++], false)
    if (built) while (built.firstChild) flow.append(built.firstChild)
    const now = performance.now()
    for (let i = start; i < spans.length; i++) {
      const at = Number(spans[i].dataset.at)
      if (at) {
        spans[i].style.animation = ''
        spans[i].style.color = ''
        spans[i].style.maskImage = ''
        spans[i].style.webkitMaskImage = ''
        spans[i].style.animationDelay = `-${Math.round(now - at)}ms`
      }
    }
    return true
  }

  function graftLine(src) {
    if (!lastSrc || lastSrc.endsWith('\n')) return false
    const delta = src.slice(lastSrc.length)
    if (!delta || delta.includes('\n')) return false
    const lineAt = src.lastIndexOf('\n') + 1
    if (lineAt !== flowAt || !flowEl || !host.contains(flowEl)) return false
    const line = src.slice(lineAt)
    if (!STRUCT.test(delta) && !/^\s*(?:[-+]|\d+\.)/.test(line) && appendToFlow(delta)) {
      lastSrc = src
      unitsDirty = true
      return true
    }
    const prev = lastSrc.slice(lastSrc.lastIndexOf('\n') + 1)
    const prevVis = visibleOf(prev)
    const nextVis = visibleOf(line)
    if (nextVis === prevVis + delta && appendToFlow(delta)) {
      lastSrc = src
      unitsDirty = true
      return true
    }
    if (!replaceOpenLine(line)) return false
    lastSrc = src
    unitsDirty = true
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
      if (!src.startsWith(lastSrc)) {
        reset()
        if (src) paint(src)
        return
      }
      if (graftLine(src)) return
      paint(src)
    },
    light(index, { durationMs, mx, my, lateMs = 0 } = {}) {
      const el = spans[index]
      if (!el) return null
      if (mx != null) el.style.setProperty('--mx', mx)
      if (my != null) el.style.setProperty('--my', my)
      if (durationMs != null) el.style.setProperty('--d', durationMs + 'ms')
      el.dataset.at = String(performance.now() - lateMs)
      el.style.animationDelay = lateMs ? `-${Math.round(lateMs)}ms` : '0ms'
      el.classList.add('on')
      return el
    },
    clear() {
      reset()
    },
  }
}
