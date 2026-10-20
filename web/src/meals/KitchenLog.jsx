import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { CATEGORY_LABELS, plateFor } from '../cards/kinds.js'
import { fetchLogPage } from './plan.js'
import { formatLogWhen } from './logDate.js'
import {
  conversationSummary,
  cookOrdinalDetail,
  entryMeta,
  entryWhen,
  foldKey,
  formatClock,
  groupLogEntries,
  RECIPE_EVENT_KINDS,
} from './logEntries.js'

// Weeks are one entry type, so one accent: rosewater, unless the tattva plugin
// colours the week (tokens in index.css).
const WEEK_TONE = ['var(--acc-rosewater)', 'var(--acc-rosewater-glyph)']

function formatRange(weekStart) {
  const a = new Date(weekStart + 'T12:00:00')
  const b = new Date(a)
  b.setDate(b.getDate() + 6)
  const sameMonth = a.getMonth() === b.getMonth()
  if (sameMonth) {
    return `${a.getDate()} – ${b.getDate()} ${b.toLocaleDateString('en-GB', { month: 'short' })}`
  }
  return `${a.getDate()} ${a.toLocaleDateString('en-GB', { month: 'short' })} – ${b.getDate()} ${b.toLocaleDateString('en-GB', { month: 'short' })}`
}

function weekSummary(nights) {
  const titles = (nights || []).map((n) => n.title).filter(Boolean)
  if (!titles.length) return 'open week'
  return titles.slice(0, 2).join(', ') + (titles.length > 2 ? '…' : '')
}

function weatherLine(weather) {
  if (!weather) return ''
  if (typeof weather.summary === 'string' && weather.summary.trim()) return weather.summary.trim()
  const days = weather.days || []
  if (!days.length) return ''
  const first = days[0]
  return [first.condition || first.summary, first.high != null ? `${Math.round(first.high)}°` : '']
    .filter(Boolean)
    .join(' · ')
}

function toneClass(kind) {
  const meta = entryMeta(kind)
  return meta.rowClass + (meta.modClass ? ' ' + meta.modClass : '')
}

function catLabel(category) {
  if (!category) return ''
  return CATEGORY_LABELS[category] || category
}

function showPlate(kind, weight, category) {
  return weight === 'key' && RECIPE_EVENT_KINDS.has(kind) && Boolean(category)
}

function childWhen(entry, block, timeZone) {
  if (entry.dateApprox) return formatLogWhen(entry.at, { approx: true })
  if (block.underDay) return formatClock(entry.at, timeZone)
  return entryWhen(entry, { underDay: false, timeZone })
}

export function LogFold({ block, timeZone, onOpen }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const tone = toneClass(block.kind)
  const quiet = block.weight === 'routine'
  const plate = showPlate(block.kind, block.weight, block.category)
  const cat = catLabel(block.category)
  return (
    <li className={'tn ' + tone + (quiet ? ' tl-quiet' : '') + (open ? ' open' : '')}>
      <span className="tdot" aria-hidden="true" />
      <button
        type="button"
        className={'tlk ' + tone + (quiet ? ' tl-quiet' : '')}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((cur) => !cur)}
      >
        {plate ? <img src={plateFor(block.category)} alt="" draggable={false} /> : null}
        <span>
          <small>
            {block.timeLabel} · {block.metaTail}
          </small>
          {block.title ? (
            <span className="trl">
              <b>{block.title}</b> {cat ? <i>{cat}</i> : null}
            </span>
          ) : null}
          {block.quiet ? <> {' '}<span className="tq">{block.quiet}</span></> : null}
          {block.more ? <i className="tmore">{block.more}</i> : null}
        </span>
        <i className="tcar" aria-hidden="true">
          ▾
        </i>
      </button>
      <div className="twb" id={panelId} hidden={!open}>
        <ol>
          {block.events.map((event, index) => (
            <li key={event.kind + event.id + event.at + index}>
              <button
                type="button"
                className="link"
                onClick={(e) => onOpen(event.kind, event.id, e.currentTarget)}
              >
                {childWhen(event, block, timeZone)}
                {event.title ? ` · ${event.title}` : ''}
                {event.kind === 'recipe_cooked' && cookOrdinalDetail(event.ordinal)
                  ? ` · ${cookOrdinalDetail(event.ordinal)}`
                  : ''}
              </button>
            </li>
          ))}
        </ol>
      </div>
    </li>
  )
}

function LogEntry({ block, onOpen }) {
  const entry = block.entry
  const tone = toneClass(entry.kind)
  const quiet = block.weight === 'routine'
  const plate = showPlate(entry.kind, block.weight, entry.category)
  const cat = RECIPE_EVENT_KINDS.has(entry.kind)
    ? catLabel(entry.category)
    : entry.kind === 'note_created'
      ? entry.type || entry.detail || ''
      : ''
  return (
    <li className={'tn ' + tone + (quiet ? ' tl-quiet' : '')}>
      <span className="tdot" aria-hidden="true" />
      <button
        type="button"
        className={'tlk ' + tone + (quiet ? ' tl-quiet' : '')}
        onClick={(e) => onOpen(entry.kind, entry.id, e.currentTarget)}
      >
        {plate ? <img src={plateFor(entry.category)} alt="" draggable={false} /> : null}
        <span>
          <small>
            {block.timeLabel} · {block.metaTail}
          </small>
          {quiet ? (
            entry.title ? <> {' '}<span className="tq">{entry.title}</span></> : null
          ) : (
            <span className="trl">
              <b>{entry.title}</b>
              {RECIPE_EVENT_KINDS.has(entry.kind) ? <> <code>{entry.id}</code></> : null}
              {cat ? <> <i>{cat}</i></> : null}
            </span>
          )}
          {!quiet && RECIPE_EVENT_KINDS.has(entry.kind) && entry.kind !== 'photo_added' && entry.kind !== 'recipe_cooked' && entry.detail ? (
            <em>{entry.detail}</em>
          ) : null}
        </span>
      </button>
    </li>
  )
}

export function KitchenLogList({ entries, timeZone, weekStart, now, onOpen, sentinelRef, ended, loading }) {
  const [openWeek, setOpenWeek] = useState(null)
  const blocks = useMemo(
    () => groupLogEntries(entries, { timeZone, weekStart, now }),
    [entries, timeZone, weekStart, now],
  )
  return (
    <ol className="tlo">
      {blocks.map((block, index) => {
        if (block.type === 'day') {
          return (
            <li key={'d-' + block.day + '-' + index} className="tn tl-day">
              <h4>{block.label}</h4>
            </li>
          )
        }
        if (block.type === 'week') {
          const entry = block.entry
          const tone = WEEK_TONE
          const open = openWeek === entry.weekStart
          const dinners = (entry.nights || []).filter((n) => n.title || n.recipe).length
          const chats = entry.conversations || []
          const chatLine = conversationSummary(chats)
          const wx = weatherLine(entry.weather)
          const tattva = entry.tattva
          return (
            <li
              key={'w-' + entry.weekStart}
              className={'tn tl-w' + (open ? ' open' : '')}
              style={{
                '--tc': tattva?.colour || tone[0],
                '--tt': tattva?.colour || tone[1],
              }}
            >
              <span className="tdot" aria-hidden="true" />
              <button
                type="button"
                className="tw"
                aria-expanded={open}
                onClick={() => setOpenWeek(open ? null : entry.weekStart)}
              >
                <span className="twh">
                  <b>{formatRange(entry.weekStart)}</b>
                  {tattva?.glyph ? (
                    <span className="twt">
                      {tattva.glyph} {tattva.name || ''}
                    </span>
                  ) : null}
                </span>
                <span className="tws">{weekSummary(entry.nights)}</span>
                <span className="twx">
                  <span>
                    {[dinners || !chatLine ? `${dinners} dinner${dinners === 1 ? '' : 's'}` : '', chatLine]
                      .filter(Boolean)
                      .join(' · ')}
                    {wx ? ` · ${wx}` : ''}
                    {entry.slipTitle ? ` · ${entry.slipTitle}` : ''}
                  </span>
                  <i className="tcar" aria-hidden="true">
                    ▾
                  </i>
                </span>
              </button>
              <div className="twb" hidden={!open}>
                <ol>
                  {(entry.nights || [])
                    .filter((n) => n.title || n.recipe)
                    .map((n) => (
                      <li key={n.date} className={n.cooked ? 'cooked' : undefined}>
                        <span>{n.title || 'open'}</span>
                        {n.recipe ? (
                          <button
                            type="button"
                            className="link"
                            onClick={(e) => {
                              e.stopPropagation()
                              onOpen('recipe_added', n.recipe, e.currentTarget)
                            }}
                          >
                            {n.recipe}
                          </button>
                        ) : null}
                      </li>
                    ))}
                  {chats.map((chat) => (
                    <li key={'chat-' + chat.id} className="twc">
                      <button
                        type="button"
                        className="link"
                        onClick={(e) => {
                          e.stopPropagation()
                          onOpen('chat', chat.id, e.currentTarget)
                        }}
                      >
                        {chat.title || 'Conversation'}
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
            </li>
          )
        }
        if (block.type === 'fold') {
          return <LogFold key={foldKey(block.events)} block={block} timeZone={timeZone} onOpen={onOpen} />
        }
        const entry = block.entry
        return <LogEntry key={entry.kind + entry.id + entry.at + index} block={block} onOpen={onOpen} />
      })}
      <li className={'tl-more' + (ended ? ' end' : '')} ref={sentinelRef} aria-hidden="true">
        <span>{ended ? 'the first page of the log' : loading ? 'loading…' : 'earlier weeks'}</span>
      </li>
    </ol>
  )
}

export function KitchenLog({ settings }) {
  const navigate = useNavigate()
  const [entries, setEntries] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loading, setLoading] = useState(false)
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState('')
  const sentinel = useRef(null)
  const busy = useRef(false)

  const loadMore = useCallback(async (reset) => {
    if (busy.current) return
    if (!reset && ended) return
    busy.current = true
    setLoading(true)
    try {
      const before = reset ? null : nextCursor
      const body = await fetchLogPage(before || undefined)
      const page = body.entries || []
      setEntries((cur) => (reset ? page : [...cur, ...page]))
      setNextCursor(body.nextCursor || null)
      setEnded(!body.nextCursor)
      setError('')
    } catch (err) {
      setError(err.message || 'Could not load the kitchen log.')
      if (reset) setEnded(true)
    } finally {
      setLoading(false)
      busy.current = false
    }
  }, [ended, nextCursor])

  useEffect(() => {
    loadMore(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (ended || !nextCursor) return undefined
    const el = sentinel.current
    if (!el) return undefined
    const io = new IntersectionObserver(
      (parts) => {
        if (parts.some((p) => p.isIntersecting)) loadMore(false)
      },
      { rootMargin: '0px 0px 400px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [ended, nextCursor, entries.length, loadMore])

  function openKind(kind, id, el) {
    if (!id) return
    rememberOrigin(el)
    if (RECIPE_EVENT_KINDS.has(kind)) navigate('/recipes/' + encodeURIComponent(id))
    else if (kind === 'note_created' || kind === 'note_archived') navigate('/notes/' + encodeURIComponent(id))
    else if (kind === 'chat') navigate('/chats/' + encodeURIComponent(id))
  }

  // Stacked under the slip (tablet, phone) the Log pages back just as it does
  // beside it: the whole timeline, older pages as you scroll to the end.
  return (
    <section className="kl tl" aria-label="Kitchen log">
      <h3>the kitchen log</h3>
      {error && <p className="tl-more end">{error}</p>}
      <KitchenLogList
        entries={entries}
        timeZone={settings?.weather?.timezone}
        weekStart={settings?.weekStart || 'sat'}
        onOpen={openKind}
        sentinelRef={sentinel}
        ended={ended}
        loading={loading}
      />
    </section>
  )
}
