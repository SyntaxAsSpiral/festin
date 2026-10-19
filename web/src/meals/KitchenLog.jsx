import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { CATEGORY_LABELS, plateFor } from '../cards/kinds.js'
import { fetchLogPage } from './plan.js'
import { formatLogWhen } from './logDate.js'
import { conversationSummary, entryMeta, RECIPE_EVENT_KINDS } from './logEntries.js'

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

function formatWhen(iso) {
  return formatLogWhen(iso)
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

export function KitchenLog() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [openWeek, setOpenWeek] = useState(null)
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
  const shown = entries

  return (
    <section className="kl tl" aria-label="Kitchen log">
      <h3>the kitchen log</h3>
      {error && <p className="tl-more end">{error}</p>}
      <ol className="tlo">
        {shown.map((entry) => {
          if (entry.kind === 'week') {
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
                      {[dinners || !chatLine ? `${dinners} dinner${dinners === 1 ? '' : 's'}` : '', chatLine].filter(Boolean).join(' · ')}
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
                                openKind('recipe_added', n.recipe, e.currentTarget)
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
                            openKind('chat', chat.id, e.currentTarget)
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

          if (entry.kind === 'note_created' || entry.kind === 'note_archived') {
            const meta = entryMeta(entry.kind)
            return (
              <li key={'n-' + entry.id + entry.at + entry.kind} className={'tn ' + meta.rowClass}>
                <span className="tdot" aria-hidden="true" />
                <button
                  type="button"
                  className={'tlk ' + meta.rowClass}
                  onClick={(e) => openKind(entry.kind, entry.id, e.currentTarget)}
                >
                  <span>
                    <small>
                      {formatWhen(entry.at)} · {meta.label}
                    </small>
                    <span className="trl">
                      <b>{entry.title}</b> <i>{entry.type || entry.detail || ''}</i>
                    </span>
                  </span>
                </button>
              </li>
            )
          }

          if (entry.kind === 'chat') {
            return (
              <li key={'c-' + entry.id + entry.at} className="tn tl-chat">
                <span className="tdot" aria-hidden="true" />
                <button
                  type="button"
                  className="tlk tl-chat"
                  onClick={(e) => openKind('chat', entry.id, e.currentTarget)}
                >
                  <span>
                    <small>
                      {formatLogWhen(entry.at, { approx: Boolean(entry.dateApprox) })} · Chat
                    </small>
                    <span className="trl">
                      <b>{entry.title}</b>
                    </span>
                  </span>
                </button>
              </li>
            )
          }

          const meta = entryMeta(entry.kind)
          const cat = CATEGORY_LABELS[entry.category] || entry.category || ''
          const showPlate = RECIPE_EVENT_KINDS.has(entry.kind) && entry.kind !== 'photo_added'
          return (
            <li
              key={'r-' + entry.id + entry.at + entry.kind}
              className={'tn ' + meta.rowClass + (meta.modClass ? ' ' + meta.modClass : '')}
            >
              <span className="tdot" aria-hidden="true" />
              <button
                type="button"
                className={'tlk ' + meta.rowClass}
                onClick={(e) => openKind(entry.kind, entry.id, e.currentTarget)}
              >
                {showPlate && entry.category ? <img src={plateFor(entry.category)} alt="" draggable={false} /> : null}
                <span>
                  <small>
                    {formatWhen(entry.at)} · {meta.label}
                    {entry.kind === 'photo_added' && entry.detail ? ` · ${entry.detail}` : ''}
                  </small>
                  <span className="trl">
                    <b>{entry.title}</b> <code>{entry.id}</code> <i>{cat}</i>
                  </span>
                  {entry.kind !== 'photo_added' && entry.detail ? <em>{entry.detail}</em> : null}
                </span>
              </button>
            </li>
          )
        })}
        <li className={'tl-more' + (ended ? ' end' : '')} ref={sentinel} aria-hidden="true">
          <span>{ended ? 'the first page of the log' : loading ? 'loading…' : 'earlier weeks'}</span>
        </li>
      </ol>
    </section>
  )
}
