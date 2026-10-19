import { useEffect, useRef } from 'react'
import { mountInkLayer } from './ink/layer.js'
import { readWritingSpeed } from './ink/speed.js'
import { renderChatMarkdown } from './markdown.js'

// Live reply host. React keeps this node; the ink layer owns its children so
// Markdown re-renders do not restart per-letter seep animations.
export function InkReply({ text, shown, plain }) {
  const hostRef = useRef(null)
  const layerRef = useRef(null)

  useEffect(() => {
    if (plain) return undefined
    const host = hostRef.current
    if (!host) return undefined
    layerRef.current = mountInkLayer(host, { plain: false })
    return () => {
      layerRef.current?.destroy()
      layerRef.current = null
    }
  }, [plain])

  useEffect(() => {
    if (plain) return
    layerRef.current?.sync(text, shown, { cps: readWritingSpeed() })
  }, [text, shown, plain])

  if (plain) {
    return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(text.slice(0, Math.floor(shown))) }} />
  }

  return <div className="markdown-body ink-host" ref={hostRef} />
}
