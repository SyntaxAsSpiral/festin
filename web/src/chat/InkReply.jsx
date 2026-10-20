import { useEffect, useRef } from 'react'
import { mountInkLayer } from './ink/layer.js'
import { renderChatMarkdown } from './markdown.js'
import { bindRevealSink, revealPace } from './revealPace.js'

const followHeight = new WeakMap()

function follow(host) {
  const scroller = host?.closest?.('.transcript')
  if (!scroller) return
  const end = scroller.lastElementChild
  if (!end) return
  const prev = followHeight.get(scroller) || 0
  const grown = scroller.scrollHeight > prev + 1
  const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight
  if (grown && distance > 4) end.scrollIntoView({ block: 'end' })
  followHeight.set(scroller, scroller.scrollHeight)
}

// Live reply host. React keeps this node; the ink layer owns its children so
// Markdown re-renders do not restart per-letter seep animations.
export function InkReply({ text, shown, plain, cps, band }) {
  const hostRef = useRef(null)
  const layerRef = useRef(null)
  const textRef = useRef(text)
  const bandRef = useRef(band)
  const cpsRef = useRef(cps)
  textRef.current = text
  bandRef.current = band
  cpsRef.current = cps

  useEffect(() => {
    if (plain) return undefined
    const host = hostRef.current
    if (!host) return undefined
    const layer = mountInkLayer(host, { plain: false })
    layerRef.current = layer
    let pulses = 0
    const off = bindRevealSink(() => {
      const shownNow = Math.max(Math.floor(revealPace.shown) || 0, 0)
      layer.sync(textRef.current, shownNow, { cps: revealPace.cps, band: bandRef.current })
      // Reading scroll height lays out the page. A few letters do not move the fold.
      pulses += 1
      if (pulses % 8 === 0) follow(host)
    })
    return () => {
      off()
      layer.destroy()
      if (layerRef.current === layer) layerRef.current = null
    }
  }, [plain])

  useEffect(() => {
    if (plain) return
    const shownNow = Math.max(Math.floor(shown) || 0, Math.floor(revealPace.shown) || 0)
    layerRef.current?.sync(text, shownNow, { cps: revealPace.cps || cps, band })
    follow(hostRef.current)
  }, [text, shown, plain, cps, band])

  if (plain) {
    return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(text.slice(0, Math.floor(shown))) }} />
  }

  return <div className="markdown-body ink-host" ref={hostRef} />
}
