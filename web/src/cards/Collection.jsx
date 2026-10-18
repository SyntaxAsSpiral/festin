import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { KINDS, loadItems, matches, plateFor } from './kinds.js'
import { rememberOrigin } from './origin.js'

const PAGE = 60

function storedLayout(kind) {
  try {
    return localStorage.getItem('festin.layout.' + kind) === 'cards' ? 'cards' : 'list'
  } catch {
    return 'list'
  }
}

function typing(el) {
  return Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
}

// One copy of the list machine per tab: Layout, Query, Results, Cursor (§4).
export function Collection({ kind, cardOpen }) {
  const spec = KINDS[kind]
  const navigate = useNavigate()
  const [items, setItems] = useState(null)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')
  const [layout, setLayout] = useState(() => storedLayout(kind))
  const [cursor, setCursor] = useState(-1)
  const [shown, setShown] = useState(PAGE)
  const search = useRef(null)
  const list = useRef(null)
  const more = useRef(null)

  useEffect(() => {
    let gone = false
    loadItems(kind).then((next) => !gone && setItems(next), () => !gone && setFailed(true))
    return () => {
      gone = true
    }
  }, [kind])

  useEffect(() => {
    try {
      localStorage.setItem('festin.layout.' + kind, layout)
    } catch {
      /* per-device nicety only */
    }
  }, [kind, layout])

  const results = useMemo(() => (items ? items.filter((it) => !query.trim() || matches(it, query)) : []), [items, query])
  useEffect(() => {
    setShown(PAGE)
    setCursor(-1)
  }, [query])

  // Render more as the end of the list scrolls into view.
  useEffect(() => {
    const el = more.current
    if (!el) return undefined
    const io = new IntersectionObserver((seen) => seen[0]?.isIntersecting && setShown((n) => n + PAGE))
    io.observe(el)
    return () => io.disconnect()
  }, [results.length, shown])

  function open(item, el) {
    rememberOrigin(el)
    navigate('/' + kind + '/' + encodeURIComponent(item.id), { state: { fromList: true } })
  }

  // Keys pause while a card is open (one card at a time).
  useEffect(() => {
    if (cardOpen) return undefined
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === '/' && !typing(event.target)) {
        event.preventDefault()
        search.current?.focus()
        return
      }
      if (typing(event.target) && !(event.target === search.current && /^(ArrowDown|Enter)$/.test(event.key))) return
      const columns = layout === 'cards' ? Math.max(1, Math.round(list.current?.clientWidth / 260) || 1) : 1
      const step = { ArrowDown: columns, j: columns, ArrowUp: -columns, k: -columns, ArrowRight: 1, ArrowLeft: -1 }[event.key]
      if (step && (layout === 'cards' || Math.abs(step) === columns)) {
        event.preventDefault()
        if (event.target === search.current) search.current.blur()
        setCursor((c) => Math.min(results.length - 1, Math.max(0, c < 0 ? 0 : c + step)))
      } else if (event.key === 'Enter' && cursor >= 0 && results[cursor]) {
        event.preventDefault()
        open(results[cursor], list.current?.querySelector('[data-cursor="true"]'))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    list.current?.querySelector('[data-cursor="true"]')?.scrollIntoView({ block: 'nearest' })
    if (cursor >= shown - 5) setShown((n) => n + PAGE)
  }, [cursor, shown])

  return (
    <section className={'collection collection-' + kind} aria-label={spec.searchLabel.replace('Search ', '')}>
      <div className="lbar">
        <input
          ref={search}
          type="search"
          className="lsearch"
          placeholder={spec.searchLabel + ' (/)'}
          aria-label={spec.searchLabel}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === 'Escape' && (setQuery(''), event.currentTarget.blur())}
        />
        {spec.canCreate && (
          <button type="button" className="lnew" onClick={(event) => (rememberOrigin(event.currentTarget), navigate('/' + kind + '/new', { state: { fromList: true } }))}>
            + new
          </button>
        )}
        <div className="llayout" role="group" aria-label="Layout">
          <button type="button" aria-pressed={layout === 'list'} onClick={() => setLayout('list')} title="List">
            ☰
          </button>
          <button type="button" aria-pressed={layout === 'cards'} onClick={() => setLayout('cards')} title="Cards">
            ▦
          </button>
        </div>
      </div>
      {failed && <p className="lstate">The kitchen did not answer. Try again in a moment.</p>}
      {!failed && !items && <p className="lstate">Opening the box…</p>}
      {items && !items.length && <p className="lstate">{spec.empty}</p>}
      {items && items.length > 0 && !results.length && <p className="lstate">Nothing by that name. Ask Babette.</p>}
      <ol ref={list} className={'nlist nlist-' + layout}>
        {results.slice(0, shown).map((item, i) => (
          <li key={item.id}>
            <button type="button" className="nitem" data-cursor={i === cursor || undefined} onClick={(event) => open(item, event.currentTarget)}>
              {layout === 'cards' && kind === 'recipes' && <img className="nplate" src={plateFor(item.raw.category)} alt="" loading="lazy" />}
              {layout === 'cards' && kind === 'notes' && <span className="nswatch" data-color={item.raw.color || 'none'} />}
              <span className="ntitle">{item.title}</span>
              <span className="nline">{item.line}</span>
              {item.tip && <span className="ntip">{item.tip}</span>}
            </button>
          </li>
        ))}
      </ol>
      {results.length > shown && <div ref={more} className="lmore" aria-hidden="true" />}
    </section>
  )
}
