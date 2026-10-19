import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { rememberOrigin } from '../cards/origin.js'
import { setActiveMealsPlan } from './activePlan.js'
import {
  DEFAULT_SLIP_TITLE,
  SLIP_TITLE_MAX,
  dayLabel,
  dayName,
  displayRecipeId,
  fetchPlan,
  formatWeekLabel,
  isoDate,
  parseRecipeId,
  planToDraft,
  savePlan,
  weekOptions,
  weekStartFor,
} from './plan.js'
import { SlipBanner } from './SlipBanner.jsx'

const SAVE_MS = 450

// The kitchen's clock, read twice a minute: the today marker moves at midnight
// and its time stays current without a reload.
function useNow(ms = 30000) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), ms)
    return () => window.clearInterval(timer)
  }, [ms])
  return now
}

// "19 October, 4:32 am" in the kitchen's time zone.
function nowLabel(now, zone) {
  const at = (opts) => {
    try {
      return now.toLocaleString('en-GB', zone ? { ...opts, timeZone: zone } : opts)
    } catch {
      return now.toLocaleString('en-GB', opts)
    }
  }
  return at({ day: 'numeric', month: 'long' }) + ', ' + at({ hour: 'numeric', minute: '2-digit', hour12: true })
}

function todayIso(zone, now = new Date()) {
  try {
    if (zone) {
      const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: zone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).formatToParts(now)
      const get = (t) => parts.find((p) => p.type === t)?.value
      return `${get('year')}-${get('month')}-${get('day')}`
    }
  } catch {
    /* fall through */
  }
  return isoDate(now)
}

function NightRow({ night, i, today, thisWeek, week, clock, recipesById, recipesByTitle, patchDays, openRecipe }) {
  const [eid, setEid] = useState(displayRecipeId(night.recipe))
  useEffect(() => {
    setEid(displayRecipeId(night.recipe))
  }, [night.recipe, night.date])

  const linked = Boolean(night.recipe)
  const isToday = night.date === today && week === thisWeek

  return (
    <div className={'row' + (night.cooked ? ' cooked' : '') + (linked ? ' linked' : '') + (isToday ? ' is-today' : '')}>
      <div className="d">
        <button
          type="button"
          className="ck"
          title={night.cooked ? 'Mark not cooked' : 'Mark cooked'}
          aria-pressed={night.cooked}
          onClick={() => patchDays(i, { cooked: !night.cooked })}
        >
          {dayName(night.date)}
        </button>
        {isToday && <span className="today">{clock}</span>}
      </div>
      <span className="n">
        <input
          className="et"
          value={night.title}
          placeholder="open"
          aria-label={dayLabel(night.date) + ' dinner'}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => {
            const title = e.target.value
            const key = title.trim().toLowerCase()
            const hits = key ? recipesByTitle?.get(key) || [] : []
            const auto = hits.length === 1 ? hits[0].id : null
            if (!title.trim()) patchDays(i, { title: '', recipe: null })
            else if (auto) patchDays(i, { title, recipe: auto })
            else patchDays(i, { title })
          }}
        />
        {linked && (
          <a
            className="rl"
            href={'/recipes/' + encodeURIComponent(night.recipe)}
            aria-label="open recipe"
            onClick={(e) => {
              e.preventDefault()
              openRecipe(night.recipe, e.currentTarget)
            }}
          >
            ↗
          </a>
        )}
      </span>
      <input
        className="eid"
        value={eid}
        placeholder="CBK-####"
        aria-label={dayLabel(night.date) + ' recipe link'}
        autoComplete="off"
        spellCheck={false}
        // Type freely ("12", "cbk 12", "CBK-0012"); the link is made on leaving
        // the field or Enter. Linking on every keystroke rewrote the field to
        // CBK-#### before a number could be finished.
        onChange={(e) => setEid(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
        }}
        onBlur={() => {
          const id = parseRecipeId(eid)
          // Not an ID: show the night's current link again rather than a blank
          // field that no longer matches the slip.
          setEid(id || (eid.trim() ? displayRecipeId(night.recipe) : ''))
          if (id) {
            const hit = recipesById?.get(id)
            patchDays(i, {
              recipe: id,
              title: night.title.trim() ? night.title : hit?.title || night.title,
            })
          } else if (!eid.trim()) {
            patchDays(i, { recipe: null })
          }
        }}
      />
    </div>
  )
}

export function Slip({ settings, recipesById, recipesByTitle }) {
  const navigate = useNavigate()
  const startDay = settings?.weekStart || 'sat'
  const zone = settings?.weather?.timezone
  const now = useNow()
  const today = todayIso(zone, now)
  const clock = nowLabel(now, zone)
  const thisWeek = isoDate(weekStartFor(today, startDay))

  const [week, setWeek] = useState(thisWeek)
  const [draft, setDraft] = useState(null)
  const [saveState, setSaveState] = useState('idle')
  const [conflictNote, setConflictNote] = useState('')
  const [loadError, setLoadError] = useState('')
  const saveTimer = useRef(0)
  const draftRef = useRef(null)
  const titleOrig = useRef('')
  const titleEl = useRef(null)
  const titleFocused = useRef(false)

  useEffect(() => {
    draftRef.current = draft
    setActiveMealsPlan(draft)
    return () => setActiveMealsPlan(null)
  }, [draft])

  // Keep the contentEditable title in sync when the week loads, without fighting typing.
  useEffect(() => {
    if (!draft || !titleEl.current || titleFocused.current) return
    const next = draft.slipTitle || DEFAULT_SLIP_TITLE
    if (titleEl.current.textContent !== next) titleEl.current.textContent = next
  }, [draft?.weekStart, draft?.updatedAt, draft?.slipTitle])

  // Settings may arrive after first paint; keep "this week" aligned.
  useEffect(() => {
    setWeek((cur) => (cur === thisWeek || !draft ? thisWeek : cur))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thisWeek])

  const load = useCallback(async (weekStart) => {
    setLoadError('')
    setSaveState('idle')
    setConflictNote('')
    try {
      const plan = await fetchPlan(weekStart)
      setDraft(planToDraft(plan))
    } catch (err) {
      setDraft(null)
      setLoadError(err.message || 'Could not load this week.')
    }
  }, [])

  useEffect(() => {
    load(week)
  }, [week, load])

  const options = useMemo(() => weekOptions(thisWeek), [thisWeek])

  const queueSave = useCallback((next) => {
    clearTimeout(saveTimer.current)
    setSaveState('pending')
    saveTimer.current = window.setTimeout(async () => {
      const body = next || draftRef.current
      if (!body) return
      try {
        const saved = await savePlan(body)
        const mapped = planToDraft(saved)
        setDraft((cur) => {
          if (!cur || cur.weekStart !== mapped.weekStart) return mapped
          const dirty =
            cur.slipTitle !== body.slipTitle ||
            cur.days.some(
              (d, i) =>
                d.title !== body.days[i].title ||
                d.recipe !== body.days[i].recipe ||
                d.cooked !== body.days[i].cooked,
            )
          if (dirty) return { ...cur, updatedAt: mapped.updatedAt }
          return mapped
        })
        setSaveState('saved')
        setConflictNote('')
      } catch (err) {
        if (err.status === 409) {
          setSaveState('conflict')
          setConflictNote(
            err.body?.error ||
              'This week was saved from another device. Reloading the latest dinners.',
          )
          try {
            const plan = await fetchPlan(body.weekStart)
            setDraft(planToDraft(plan))
          } catch {
            /* keep conflict note */
          }
        } else {
          setSaveState('idle')
          setConflictNote(err.message || 'Save failed.')
        }
      }
    }, SAVE_MS)
  }, [])

  useEffect(() => () => clearTimeout(saveTimer.current), [])

  function patchDays(index, patch) {
    setDraft((cur) => {
      if (!cur) return cur
      const days = cur.days.map((d, i) => (i === index ? { ...d, ...patch } : d))
      const next = { ...cur, days }
      queueSave(next)
      return next
    })
  }

  function onTitleCommit(el) {
    const text = el.textContent.replace(/\s+/g, ' ').trim().slice(0, SLIP_TITLE_MAX)
    el.textContent = text || DEFAULT_SLIP_TITLE
    setDraft((cur) => {
      if (!cur) return cur
      const next = { ...cur, slipTitle: text || DEFAULT_SLIP_TITLE }
      queueSave(next)
      return next
    })
  }

  function openRecipe(id, el) {
    if (!id) return
    rememberOrigin(el)
    navigate('/recipes/' + encodeURIComponent(id))
  }

  if (loadError) {
    return (
      <div className="slipw">
        <div className="slip">
          <p className="close" data-state="conflict">
            {loadError}
          </p>
        </div>
      </div>
    )
  }

  if (!draft) {
    return (
      <div className="slipw">
        <div className="slip">
          <p className="close">Loading this week…</p>
        </div>
      </div>
    )
  }

  const status =
    saveState === 'conflict'
      ? conflictNote
      : saveState === 'pending'
        ? 'Saving…'
        : conflictNote || ''

  const weekLabel = formatWeekLabel(week, thisWeek).replace(/ \(this week\)$/, '')

  return (
    <div className="slipw">
      <div className="slip" id="slip">
        <SlipBanner />
        <h2
          ref={titleEl}
          className="slipT"
          contentEditable
          suppressContentEditableWarning
          spellCheck={false}
          role="textbox"
          aria-label="Slip title (click to edit)"
          onFocus={(e) => {
            titleFocused.current = true
            titleOrig.current = e.currentTarget.textContent
          }}
          onBlur={(e) => {
            titleFocused.current = false
            onTitleCommit(e.currentTarget)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              e.currentTarget.blur()
            } else if (e.key === 'Escape') {
              e.preventDefault()
              e.currentTarget.textContent = titleOrig.current
              e.currentTarget.blur()
            }
          }}
          onInput={(e) => {
            const t = e.currentTarget.textContent
            if (t.length > SLIP_TITLE_MAX) e.currentTarget.textContent = t.slice(0, SLIP_TITLE_MAX)
          }}
        />
        <div className="wk">
          <span className="wkp">
            the week of {weekLabel}
            <span className="tri" aria-hidden="true">
              ▾
            </span>
            <select
              id="wkSel"
              aria-label="Meal plan week"
              value={week}
              onChange={(e) => setWeek(e.target.value)}
            >
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
        </div>
        <div className="orn" aria-hidden="true">
          ❦
        </div>
        {draft.days.map((night, i) => (
          <NightRow
            key={night.date}
            night={night}
            i={i}
            today={today}
            thisWeek={thisWeek}
            week={week}
            clock={clock}
            recipesById={recipesById}
            recipesByTitle={recipesByTitle}
            patchDays={patchDays}
            openRecipe={openRecipe}
          />
        ))}
        <div className="orn" aria-hidden="true">
          ❦
        </div>
        <p
          className="close"
          data-state={saveState === 'conflict' ? 'conflict' : saveState === 'pending' ? 'pending' : undefined}
        >
          {status}
        </p>
      </div>
    </div>
  )
}
