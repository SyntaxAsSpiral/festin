import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { KINDS, loadItems, matches, plateFor } from './kinds.js'
import { rememberOrigin } from './origin.js'

const PAGE = 60
const CARD_MIN = 230 // narrowest card column, px
const CARD_GAP = 16

// How many card columns fit the list's width.
function useColumns(ref, active) {
  const [columns, setColumns] = useState(1)
  useEffect(() => {
    const el = ref.current
    if (!active || !el) return undefined
    const measure = () => setColumns(Math.max(1, Math.floor((el.clientWidth + CARD_GAP) / (CARD_MIN + CARD_GAP))))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref, active])
  return columns
}

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
export function Collection({ kind, cardOpen, revision = 0 }) {
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
  const cardColumns = useColumns(list, layout === 'cards')
  const columnCount = layout === 'cards' ? cardColumns : 1
  const more = useRef(null)

  // Chats search on the server (the list row has no transcript). Recipes and notes
  // come back with their text, so the filter stays on this page.
  const serverQuery = kind === 'chats' ? query.trim() : ''
  useEffect(() => {
    let gone = false
    const timer = setTimeout(() => {
      loadItems(kind, serverQuery).then(
        (next) => {
          if (!gone) {
            setItems(next)
            setFailed(false)
          }
        },
        () => !gone && setFailed(true),
      )
    }, serverQuery ? 160 : 0)
    return () => {
      gone = true
      clearTimeout(timer)
    }
  }, [kind, serverQuery, revision])

  useEffect(() => {
    try {
      localStorage.setItem('festin.layout.' + kind, layout)
    } catch {
      /* per-device nicety only */
    }
  }, [kind, layout])

  const results = useMemo(() => {
    if (!items) return []
    if (kind === 'chats' || !query.trim()) return items
    return items.filter((it) => matches(it, query))
  }, [items, query, kind])
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
      const columns = layout === 'cards' ? cardColumns : 1
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
      {items && !results.length && query.trim() && <p className="lstate">Nothing by that name. Ask Babette.</p>}
      {items && !items.length && !query.trim() && <p className="lstate">{spec.empty}</p>}
      <div ref={list} className={'nlist nlist-' + layout}>
        {/* Cards are dealt round-robin into columns, so they read left to right and
            each keeps its own height (masonry); the list is a single column. */}
        {Array.from({ length: columnCount }, (_, col) => (
          <ol key={col} className="ncol">
            {results.slice(0, shown).map((item, i) => {
              if (i % columnCount !== col) return null
              const face = layout === 'cards' && item.card ? { ...item, ...item.card } : item
              return (
                <li key={item.id}>
                  <button type="button" className="nitem" data-cursor={i === cursor || undefined} onClick={(event) => open(item, event.currentTarget)}>
                    {layout === 'cards' && kind === 'recipes' && <img className="nplate" src={plateFor(item.raw.category)} alt="" loading="lazy" />}
                    {layout === 'cards' && kind === 'notes' && <span className="nswatch" data-color={item.raw.color || 'none'} />}
                    <span className="nhead">
                      <span className="ntitle">{face.title}</span>
                      {kind === 'recipes' && <span className="nid">{item.id}</span>}
                    </span>
                    <span className="nline">{face.line}</span>
                    {face.tip && <span className="ntip">{face.tip}</span>}
                  </button>
                </li>
              )
            })}
          </ol>
        ))}
      </div>
      {results.length > shown && <div ref={more} className="lmore" aria-hidden="true" />}
    </section>
  )
}
