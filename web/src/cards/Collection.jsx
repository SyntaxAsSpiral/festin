import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { CATEGORY_LABELS, KINDS, loadItems, matches, setRecipeFavourite, setRecipeQueued } from './kinds.js'
import { rememberOrigin } from './origin.js'
import {
  defaultChoice,
  applySortFilter,
  isDefaultChoice,
  readStoredChoice,
  summarizeChoice,
  writeStoredChoice,
} from './sortfilter.js'

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

// Card view unless this device chose the list.
// Each card kind wears one piece of stationery trim at its top edge: notes a doily,
// recipes a gilt index-card rule, chats a printer's fleuron (chosen by the chat's id,
// so each chat keeps its own).
const FLEURONS = ['❦', '❧', '✾', '❁', '✿', '⁂', '❀', '☙']

function fleuronFor(id) {
  let h = 0
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return FLEURONS[h % FLEURONS.length]
}

// Only a view the cook picked is remembered (per device). Otherwise phones start
// in list, where cards would be one column anyway, and larger screens in cards.
const LAYOUT_KEY = 'festin.layout.'
const PHONE = '(max-width: 560px)'

function storedLayout(kind) {
  try {
    const picked = localStorage.getItem(LAYOUT_KEY + kind)
    if (picked === 'list' || picked === 'cards') return picked
  } catch {
    /* per-device nicety only */
  }
  return window.matchMedia?.(PHONE).matches ? 'list' : 'cards'
}

function rememberLayout(kind, layout) {
  try {
    localStorage.setItem(LAYOUT_KEY + kind, layout)
  } catch {
    /* per-device nicety only */
  }
}

function typing(el) {
  return Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
}

/** Small drawn thumbtack for pinned notes — drawn glyph, not an emoji. */
function PinMark() {
  return (
    <svg className="npin" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">
      <path d="M3.8 1.8h4.4v1.1H3.8z" fill="currentColor" />
      <path d="M4.4 2.9h3.2l-.55 2.35c.55.3.9.85.9 1.45v.4H6.35V11H5.65V7.1H3.95v-.4c0-.6.35-1.15.9-1.45L4.4 2.9z" fill="currentColor" />
    </svg>
  )
}

// One copy of the list machine per tab: Layout, Query, Results, Cursor (§4).
export function Collection({ kind, cardOpen, revision = 0 }) {
  const spec = KINDS[kind]
  const navigate = useNavigate()
  const [items, setItems] = useState(null)
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState('')
  const [layout, setLayout] = useState(() => storedLayout(kind))
  const [choice, setChoice] = useState(() => readStoredChoice(kind))
  const [sortOpen, setSortOpen] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const [shown, setShown] = useState(PAGE)
  const search = useRef(null)
  const list = useRef(null)
  const sortWrap = useRef(null)
  const cardColumns = useColumns(list, layout === 'cards')
  const columnCount = layout === 'cards' ? cardColumns : 1
  const more = useRef(null)
  const canSort = kind === 'recipes' || kind === 'notes' || kind === 'chats'

  // The row's heart toggles in place; a stale row (changed elsewhere) reloads the list.
  const [reload, setReload] = useState(0)
  function toggleFavourite(item) {
    setRecipeFavourite(item.raw, !item.raw.favourite).then(
      (saved) =>
        setItems((cur) =>
          cur.map((it) => (it.id === item.id ? { ...it, raw: { ...it.raw, favourite: saved.favourite, updatedAt: saved.updatedAt } } : it)),
        ),
      () => setReload((n) => n + 1),
    )
  }

  function toggleQueued(item) {
    setRecipeQueued(item.raw, !item.raw.queuedAt).then(
      (saved) =>
        setItems((cur) =>
          cur.map((it) =>
            it.id === item.id
              ? { ...it, raw: { ...it.raw, queuedAt: saved.queuedAt, updatedAt: saved.updatedAt } }
              : it,
          ),
        ),
      () => setReload((n) => n + 1),
    )
  }

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
  }, [kind, serverQuery, revision, reload])


  useEffect(() => {
    if (!canSort) return
    writeStoredChoice(kind, choice)
  }, [kind, choice, canSort])

  useEffect(() => {
    setChoice(readStoredChoice(kind))
    setSortOpen(false)
  }, [kind, canSort])

  const results = useMemo(() => {
    if (!items) return []
    const matched = kind === 'chats' || !query.trim() ? items : items.filter((it) => matches(it, query))
    return canSort ? applySortFilter(matched, choice, kind) : matched
  }, [items, query, kind, choice, canSort])
  useEffect(() => {
    setShown(PAGE)
    setCursor(-1)
  }, [query, choice])

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
      if (sortOpen && event.key === 'Escape') {
        event.preventDefault()
        setSortOpen(false)
        return
      }
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
    if (!sortOpen) return undefined
    function onPointer(event) {
      if (sortWrap.current && !sortWrap.current.contains(event.target)) setSortOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [sortOpen])

  useEffect(() => {
    list.current?.querySelector('[data-cursor="true"]')?.scrollIntoView({ block: 'nearest' })
    if (cursor >= shown - 5) setShown((n) => n + PAGE)
  }, [cursor, shown])

  const summary = canSort ? summarizeChoice(choice, kind) : ''

  function setSort(sort) {
    setChoice((c) => ({ ...c, sort }))
  }

  function setCategory(category) {
    setChoice((c) => ({ ...c, category }))
  }

  function setShowArchived(showArchived) {
    setChoice((c) => ({ ...c, showArchived }))
  }

  function setFavouritesOnly(favouritesOnly) {
    setChoice((c) => ({ ...c, favouritesOnly }))
  }

  function setToCookOnly(toCookOnly) {
    setChoice((c) => ({ ...c, toCookOnly }))
  }

  function setNeverCookedOnly(neverCookedOnly) {
    setChoice((c) => ({ ...c, neverCookedOnly }))
  }

  function setForm(form) {
    setChoice((c) => ({ ...c, form }))
  }

  function clearChoice() {
    setChoice(defaultChoice(kind))
    setSortOpen(false)
  }

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
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            if (sortOpen) {
              setSortOpen(false)
              return
            }
            setQuery('')
            event.currentTarget.blur()
          }}
        />
        {summary && (
          <span className="lsort-sum">
            <span>{summary}</span>
            <button type="button" className="lsort-clear" aria-label="Clear sort and filter" title="Clear" onClick={clearChoice}>
              ×
            </button>
          </span>
        )}
        <div className="lbar-tools">
          {spec.canCreate && (
            <button type="button" className="lnew" onClick={(event) => (rememberOrigin(event.currentTarget), navigate('/' + kind + '/new', { state: { fromList: true } }))}>
              + new
            </button>
          )}
          {canSort && (
            <div className="lsort" ref={sortWrap}>
              <button
                type="button"
                className="lsort-btn"
                aria-expanded={sortOpen}
                aria-controls="lsort-panel"
                aria-haspopup="dialog"
                aria-pressed={!isDefaultChoice(choice, kind)}
                title="Sort and filter"
                onClick={() => setSortOpen((o) => !o)}
              >
                ⇅
              </button>
              {sortOpen && (
                <div id="lsort-panel" className="lsort-panel" role="dialog" aria-label="Sort and filter">
                  <fieldset className="lsort-field">
                    <legend>Sort</legend>
                    {kind === 'chats' && (
                      <>
                        <label className="lsort-opt">
                          <input type="radio" name="lsort-sort" checked={choice.sort === 'date-newest'} onChange={() => setSort('date-newest')} />
                          Most recent first
                        </label>
                        <label className="lsort-opt">
                          <input type="radio" name="lsort-sort" checked={choice.sort === 'date-oldest'} onChange={() => setSort('date-oldest')} />
                          Oldest first
                        </label>
                      </>
                    )}
                    <label className="lsort-opt">
                      <input type="radio" name="lsort-sort" checked={choice.sort === 'name'} onChange={() => setSort('name')} />
                      Name (A–Z)
                    </label>
                    {kind === 'recipes' && (
                      <>
                        <label className="lsort-opt">
                          <input type="radio" name="lsort-sort" checked={choice.sort === 'id-newest'} onChange={() => setSort('id-newest')} />
                          ID, newest first
                        </label>
                        <label className="lsort-opt">
                          <input type="radio" name="lsort-sort" checked={choice.sort === 'id-oldest'} onChange={() => setSort('id-oldest')} />
                          ID, oldest first
                        </label>
                      </>
                    )}
                  </fieldset>
                  {kind === 'recipes' && (
                    <label className="lsort-cat">
                      <span>Category</span>
                      <select value={choice.category} onChange={(event) => setCategory(event.target.value)} aria-label="Filter by category">
                        <option value="">All</option>
                        {Object.entries(CATEGORY_LABELS).map(([id, label]) => (
                          <option key={id} value={id}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {kind === 'recipes' && (
                    <fieldset className="lsort-field">
                      <legend>Form</legend>
                      <label className="lsort-opt">
                        <input type="radio" name="lsort-form" checked={!choice.form} onChange={() => setForm('')} />
                        All
                      </label>
                      <label className="lsort-opt">
                        <input type="radio" name="lsort-form" checked={choice.form === 'formule'} onChange={() => setForm('formule')} />
                        Formule
                      </label>
                      <label className="lsort-opt">
                        <input type="radio" name="lsort-form" checked={choice.form === 'praxis'} onChange={() => setForm('praxis')} />
                        Praxis
                      </label>
                    </fieldset>
                  )}
                  {kind === 'recipes' && (
                    <>
                      <label className="lsort-opt">
                        <input type="checkbox" checked={Boolean(choice.favouritesOnly)} onChange={(event) => setFavouritesOnly(event.target.checked)} />
                        Favourites only
                      </label>
                      <label className="lsort-opt">
                        <input type="checkbox" checked={Boolean(choice.toCookOnly)} onChange={(event) => setToCookOnly(event.target.checked)} />
                        To cook
                      </label>
                      <label className="lsort-opt">
                        <input type="checkbox" checked={Boolean(choice.neverCookedOnly)} onChange={(event) => setNeverCookedOnly(event.target.checked)} />
                        Never cooked
                      </label>
                    </>
                  )}
                  {kind === 'notes' && (
                    <label className="lsort-opt">
                      <input type="checkbox" checked={Boolean(choice.showArchived)} onChange={(event) => setShowArchived(event.target.checked)} />
                      Show archived
                    </label>
                  )}
                </div>
              )}
            </div>
          )}
          <div className="llayout" role="group" aria-label="Layout">
            <button type="button" aria-pressed={layout === 'list'} onClick={() => (rememberLayout(kind, 'list'), setLayout('list'))} title="List">
              ☰
            </button>
            <button type="button" aria-pressed={layout === 'cards'} onClick={() => (rememberLayout(kind, 'cards'), setLayout('cards'))} title="Cards">
              ▦
            </button>
          </div>
        </div>
      </div>
      {failed && <p className="lstate">The kitchen did not answer. Try again in a moment.</p>}
      {!failed && !items && <p className="lstate">Opening the box…</p>}
      {items && !results.length && query.trim() && <p className="lstate">Nothing by that name. Ask Babette.</p>}
      {items && !results.length && !query.trim() && items.length > 0 && summary && kind === 'recipes' && (
        <p className="lstate">Nothing matches that filter.</p>
      )}
      {items && !results.length && !query.trim() && items.length > 0 && kind === 'notes' && !choice.showArchived && (
        <p className="lstate">Nothing pinned. Show archived, or write a note.</p>
      )}
      {items && !items.length && !query.trim() && <p className="lstate">{spec.empty}</p>}
      <div ref={list} className={'nlist nlist-' + layout}>
        {/* Cards are dealt round-robin into columns, so they read left to right and
            each keeps its own height (masonry); the list is a single column. */}
        {Array.from({ length: columnCount }, (_, col) => (
          <ol key={col} className="ncol">
            {results.slice(0, shown).map((item, i) => {
              if (i % columnCount !== col) return null
              const face = layout === 'cards' && item.card ? { ...item, ...item.card } : item
              const archived = kind === 'notes' && item.raw && !item.raw.open
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={
                      'nitem' +
                      (archived ? ' nitem-archived' : '') +
                      (kind === 'recipes' && item.raw?.favourite ? ' nitem-fav' : '') +
                      (kind === 'recipes' && item.raw?.queuedAt ? ' nitem-queued' : '') +
                      (kind === 'recipes' && item.raw?.kind === 'praxis' ? ' nitem-praxis' : '')
                    }
                    data-cursor={i === cursor || undefined}
                    onClick={(event) => open(item, event.currentTarget)}
                  >
                    {layout === 'cards' && kind === 'notes' && <span className="nswatch" data-color={item.raw.color || 'none'} />}
                    {layout === 'cards' && kind === 'chats' && (
                      <span className="ntrim-fleuron" aria-hidden="true">
                        {fleuronFor(item.id)}
                      </span>
                    )}
                    <span className="nhead">
                      <span className="ntitle">
                        {kind === 'notes' && item.raw?.open && <PinMark />}
                        {face.title}
                      </span>
                      {kind === 'recipes' && <span className="nid">{item.id}</span>}
                    </span>
                    {layout === 'cards' && kind === 'recipes' ? (
                      <>
                        {/* The category with its engraved icon; where it came from on a line of its own. */}
                        <span className="nline ncat">
                          <i
                            className="ncat-icon"
                            aria-hidden="true"
                            style={{ '--icon': `url(/art/icons/${CATEGORY_LABELS[item.raw?.category] ? item.raw.category : 'uncategorized'}.svg)` }}
                          />
                          {CATEGORY_LABELS[item.raw?.category] || 'Uncategorized'}
                        </span>
                        {String(face.line || '').replace(/^[^,]*,?\s*/, '') && (
                          <span className="nline nfrom">{String(face.line || '').replace(/^[^,]*,?\s*/, '')}</span>
                        )}
                      </>
                    ) : (
                      <span className="nline">{face.line}</span>
                    )}
                    {face.tip && <span className="ntip">{face.tip}</span>}
                  </button>
                  {kind === 'recipes' && (
                    <>
                      <button
                        type="button"
                        className={'nfav' + (item.raw?.favourite ? ' on' : '')}
                        aria-pressed={Boolean(item.raw?.favourite)}
                        aria-label={(item.raw?.favourite ? 'Unfavourite ' : 'Favourite ') + item.title}
                        onClick={() => toggleFavourite(item)}
                      >
                        {item.raw?.favourite ? '♥' : '♡'}
                      </button>
                      <button
                        type="button"
                        className={'nqueue' + (item.raw?.queuedAt ? ' on' : '')}
                        aria-pressed={Boolean(item.raw?.queuedAt)}
                        aria-label={(item.raw?.queuedAt ? 'Remove from to-cook: ' : 'To cook: ') + item.title}
                        onClick={() => toggleQueued(item)}
                      >
                        {item.raw?.queuedAt ? '⚑' : '⚐'}
                      </button>
                    </>
                  )}
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
