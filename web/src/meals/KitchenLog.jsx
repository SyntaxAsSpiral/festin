import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { CATEGORY_LABELS, plateFor } from '../cards/kinds.js'
import { fetchLogPage } from './plan.js'

const WEEK_TONE = [
  ['#8b5365', '#8b5365'],
  ['#a58a53', '#a58a53'],
  ['#68634f', '#68634f'],
  ['#7f805d', '#7f805d'],
  ['#9f8b83', '#9f8b83'],
]

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
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10)
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '')
  const hasTime = /T\d{2}:/.test(iso) && !iso.endsWith('T23:59:59.000000Z')
  if (!hasTime) return day
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${day} · ${time}`
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
  const [sideBySide, setSideBySide] = useState(false)
  const sentinel = useRef(null)
  const busy = useRef(false)

  useEffect(() => {
    const main = document.querySelector('.main')
    if (!main || typeof ResizeObserver === 'undefined') return undefined
    const apply = () => setSideBySide(main.clientWidth >= 780)
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(main)
    return () => ro.disconnect()
  }, [])

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
    if (!sideBySide || ended || !nextCursor) return undefined
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
  }, [sideBySide, ended, nextCursor, entries.length, loadMore])

  function openKind(kind, id, el) {
    if (!id) return
    rememberOrigin(el)
    if (kind === 'recipe_added' || kind === 'recipe_edited') navigate('/recipes/' + encodeURIComponent(id))
    else if (kind === 'note_created') navigate('/notes/' + encodeURIComponent(id))
    else if (kind === 'chat') navigate('/chats/' + encodeURIComponent(id))
  }

  const shown = sideBySide ? entries : entries.slice(0, 8)

  return (
    <section className="kl tl" aria-label="Kitchen log">
      <h3>the kitchen log</h3>
      {error && <p className="tl-more end">{error}</p>}
      <ol className="tlo">
        {shown.map((entry, index) => {
          if (entry.kind === 'week') {
            const tone = WEEK_TONE[index % WEEK_TONE.length]
            const open = openWeek === entry.weekStart
            const dinners = (entry.nights || []).filter((n) => n.title || n.recipe).length
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
                      {dinners} dinner{dinners === 1 ? '' : 's'}
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
                  </ol>
                </div>
              </li>
            )
          }

          if (entry.kind === 'note_created') {
            return (
              <li key={'n-' + entry.id + entry.at} className="tn tl-c">
                <span className="tdot" aria-hidden="true" />
                <button
                  type="button"
                  className="tlk tl-c"
                  onClick={(e) => openKind('note_created', entry.id, e.currentTarget)}
                >
                  <span>
                    <small>{formatWhen(entry.at)} · Note created</small>
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
                      {formatWhen(entry.at)} · Chat{entry.dateApprox ? ' · around' : ''}
                    </small>
                    <span className="trl">
                      <b>{entry.title}</b>
                    </span>
                  </span>
                </button>
              </li>
            )
          }

          const label = entry.kind === 'recipe_added' ? 'Added' : 'Updated'
          const cat = CATEGORY_LABELS[entry.category] || entry.category || ''
          return (
            <li key={'r-' + entry.id + entry.at + entry.kind} className={'tn tl-r tl-' + (entry.kind === 'recipe_added' ? 'a' : 'u')}>
              <span className="tdot" aria-hidden="true" />
              <button
                type="button"
                className="tlk tl-r"
                onClick={(e) => openKind(entry.kind, entry.id, e.currentTarget)}
              >
                {entry.category ? <img src={plateFor(entry.category)} alt="" draggable={false} /> : null}
                <span>
                  <small>
                    {formatWhen(entry.at)} · {label}
                  </small>
                  <span className="trl">
                    <b>{entry.title}</b> <code>{entry.id}</code> <i>{cat}</i>
                  </span>
                  {entry.detail ? <em>{entry.detail}</em> : null}
                </span>
              </button>
            </li>
          )
        })}
        {sideBySide && (
          <li
            className={'tl-more' + (ended ? ' end' : '')}
            ref={sentinel}
            aria-hidden="true"
          >
            <span>{ended ? 'the first page of the log' : loading ? 'loading…' : 'earlier weeks'}</span>
          </li>
        )}
        {!sideBySide && ended && (
          <li className="tl-more end" aria-hidden="true">
            <span>the first page of the log</span>
          </li>
        )}
      </ol>
    </section>
  )
}
