import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useSurface } from '../chat/Surface.jsx'
import { WET_BAND_MAX } from '../chat/ink/constants.js'
import { MOTION_KEY, prefersReducedMotion } from '../useReducedMotion.js'
import {
  fetchContextLanes,
  fetchPlugins,
  fetchSettings,
  rotateInboxKey,
  saveContextLane,
  saveModelKey,
  saveSettings,
  testModel,
} from './api.js'
import {
  CONTEXT_LANES,
  OPENROUTER_BASE,
  SETTINGS_TABS,
  WEEK_STARTS,
  baseUrlForProvider,
  draftFromSettings,
  inboxKeyBlock,
  keySourceMessage,
  lanePreview,
  parseSettingsTab,
  providerOf,
} from './form.js'
import { PluginPanel } from './PluginPanel.jsx'
import './settings.css'

const NARROW = '(max-width: 900px)'
const EMPTY_DRAFT = draftFromSettings({})

function calmStatus(status) {
  return (
    status === 'Saved.' ||
    status === 'Key stored.' ||
    status === 'Key cleared.' ||
    status === 'Inbox key minted.' ||
    status.startsWith('Connected.')
  )
}

function typingTarget(el) {
  return Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
}

function cardOpen() {
  return Boolean(document.querySelector('.card-layer .card, .confirm'))
}

function setMotionLocal(on) {
  try {
    localStorage.setItem(MOTION_KEY, on ? 'on' : 'off')
  } catch {
    /* private mode */
  }
  document.documentElement.dataset.motion = on ? 'on' : 'off'
  window.dispatchEvent(new Event('festin-motion'))
}

export function useOpenSettings() {
  const [params, setParams] = useSearchParams()
  const { tuck } = useSurface()
  return useCallback(
    (next = 'model') => {
      if (window.matchMedia(NARROW).matches) tuck()
      const copy = new URLSearchParams(params)
      copy.set('settings', parseSettingsTab(next) || 'model')
      setParams(copy, { replace: true })
    },
    [params, setParams, tuck],
  )
}

export function useSettingsOpen() {
  const [params] = useSearchParams()
  return Boolean(parseSettingsTab(params.get('settings')))
}

export function SettingsSidebar() {
  const [params, setParams] = useSearchParams()
  const tab = parseSettingsTab(params.get('settings'))
  const open = Boolean(tab)
  const { tuck } = useSurface()
  const panel = useRef(null)
  const draftRef = useRef(EMPTY_DRAFT)
  const [draft, setDraftState] = useState(EMPTY_DRAFT)
  const [lanes, setLanes] = useState({})
  const [editing, setEditing] = useState(null)
  const [editText, setEditText] = useState('')
  const [plugins, setPlugins] = useState({ status: 'loading', plugins: [] })
  const [status, setStatus] = useState('')
  const [keyText, setKeyText] = useState('')
  const [inboxSecret, setInboxSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [motionOn, setMotionOn] = useState(() => !prefersReducedMotion())

  const setDraft = useCallback((next) => {
    const value = typeof next === 'function' ? next(draftRef.current) : next
    draftRef.current = value
    setDraftState(value)
  }, [])

  const setTab = useCallback(
    (next) => {
      const copy = new URLSearchParams(params)
      if (!next) copy.delete('settings')
      else copy.set('settings', next)
      setParams(copy, { replace: true })
    },
    [params, setParams],
  )

  const close = useCallback(() => setTab(null), [setTab])

  const load = useCallback(async () => {
    setStatus('')
    try {
      const [settings, context, plug] = await Promise.all([
        fetchSettings(),
        fetchContextLanes(),
        fetchPlugins(),
      ])
      setDraft(settings)
      setLanes(context)
      setPlugins(plug)
    } catch (err) {
      setStatus(err.message || 'Could not load settings.')
      setDraft(EMPTY_DRAFT)
    }
  }, [setDraft])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  useEffect(() => {
    const sync = () => setMotionOn(!prefersReducedMotion())
    sync()
    window.addEventListener('festin-motion', sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener('festin-motion', sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  useEffect(() => {
    function onKey(event) {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === ',' && !event.shiftKey) {
        if (typingTarget(event.target)) return
        event.preventDefault()
        if (open) close()
        else {
          if (window.matchMedia(NARROW).matches) tuck()
          setTab('model')
        }
        return
      }
      if (event.key !== 'Escape' || !open) return
      if (typingTarget(event.target) && panel.current?.contains(event.target)) {
        event.preventDefault()
        event.stopPropagation()
        event.target.blur()
        return
      }
      if (cardOpen()) return
      event.preventDefault()
      event.stopPropagation()
      close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close, setTab, tuck])

  useEffect(() => {
    if (!open) return undefined
    function onPointer(event) {
      const el = event.target
      if (!(el instanceof Element)) return
      if (panel.current?.contains(el) || el.closest('#gear')) return
      close()
    }
    document.addEventListener('pointerdown', onPointer, true)
    return () => document.removeEventListener('pointerdown', onPointer, true)
  }, [open, close])

  async function persist(nextDraft) {
    setBusy(true)
    setStatus('')
    const result = await saveSettings(nextDraft, nextDraft.updatedAt)
    setBusy(false)
    if (!result.ok) {
      setStatus(result.error)
      return result
    }
    setDraft(draftFromSettings(result.body))
    setStatus('Saved.')
    window.dispatchEvent(new Event('festin-settings'))
    return result
  }

  async function commitKey(value) {
    setBusy(true)
    const result = await saveModelKey(value)
    setBusy(false)
    if (!result.ok) {
      setStatus(result.error)
      return
    }
    setKeyText('')
    setDraft(draftFromSettings(result.body))
    setStatus(String(value || '').trim() ? 'Key stored.' : 'Key cleared.')
  }

  async function runTest() {
    setBusy(true)
    const result = await testModel()
    setBusy(false)
    const message = (result.body && result.body.message) || result.error || 'The model test failed.'
    setStatus(message)
  }

  async function mintInboxKey() {
    setBusy(true)
    setInboxSecret('')
    const result = await rotateInboxKey()
    setBusy(false)
    if (!result.ok) {
      setStatus(result.error)
      return
    }
    setDraft(draftFromSettings(result.body))
    setInboxSecret(inboxKeyBlock(result.body?.inboxKey))
    setStatus('Inbox key minted.')
  }

  function patch(partial) {
    const next = { ...draftRef.current, ...partial }
    setDraft(next)
    void persist(next)
  }

  function onProvider(value) {
    const modelBaseUrl = baseUrlForProvider(value, draftRef.current.modelBaseUrl)
    patch({ modelBaseUrl: modelBaseUrl || OPENROUTER_BASE })
  }

  async function commitLane(key) {
    const laneMeta = CONTEXT_LANES.find((item) => item.key === key)
    const lane = lanes[key] || { section: laneMeta.key, text: '', updatedAt: null, missing: true }
    setBusy(true)
    const result = await saveContextLane({ ...lane, key: laneMeta.key }, editText, lane.updatedAt)
    setBusy(false)
    if (!result.ok) {
      setStatus(result.error)
      return
    }
    setLanes((current) => ({
      ...current,
      [key]: {
        section: result.body.section || key,
        text: result.body.text,
        updatedAt: result.body.updatedAt,
        missing: false,
      },
    }))
    setEditing(null)
    setStatus('Saved.')
  }

  const provider = providerOf(draft.modelBaseUrl)

  return (
    <div
      ref={panel}
      id="sidebar"
      className={open ? 'open' : undefined}
      role="dialog"
      aria-modal="false"
      aria-labelledby="sbT"
      data-settings
    >
      <div className="sbh">
        <h2 id="sbT">Settings</h2>
        <button type="button" className="sbx" aria-label="Close settings" title="Close (Esc)" onClick={close}>
          ×
        </button>
      </div>
      {status && (
        <p className={'status-line' + (calmStatus(status) ? '' : ' err')} role="status">
          {status}
        </p>
      )}
      <div className="stabs" role="tablist" aria-label="Settings">
        {SETTINGS_TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={'st-' + id}
            aria-controls={'sp-' + id}
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
          >
            {id === 'model' ? 'Model' : id === 'context' ? 'Context' : 'Plugins'}
          </button>
        ))}
      </div>
      <div className="sbody">
        {tab === 'model' && (
          <div role="tabpanel" id="sp-model" aria-labelledby="st-model">
            <section className="sg" aria-labelledby="sh-conv">
              <h3 id="sh-conv">Conversation</h3>
              <p className="fine">
                Connect to a custom endpoint or OpenRouter. Choose a model with tool support and vision for cooking
                photos.
              </p>
              <div className="sfr">
                <div className="sf">
                  <label htmlFor="s-provider">Connection</label>
                  <select id="s-provider" value={provider} onChange={(e) => onProvider(e.target.value)} disabled={busy}>
                    <option value="local">Custom</option>
                    <option value="openrouter">OpenRouter</option>
                  </select>
                </div>
                <div className="sf">
                  <label htmlFor="s-model">Model name</label>
                  <input
                    id="s-model"
                    value={draft.modelName}
                    placeholder="model-id"
                    spellCheck={false}
                    autoCapitalize="none"
                    autoComplete="off"
                    onChange={(e) => setDraft({ ...draftRef.current, modelName: e.target.value })}
                    onBlur={() => persist(draftRef.current)}
                    disabled={busy}
                  />
                </div>
              </div>
              <div className="sf">
                <label htmlFor="s-base">API base URL</label>
                <input
                  id="s-base"
                  value={draft.modelBaseUrl}
                  placeholder={provider === 'openrouter' ? OPENROUTER_BASE : 'http://127.0.0.1:1234/v1'}
                  inputMode="url"
                  spellCheck={false}
                  autoCapitalize="none"
                  autoComplete="off"
                  onChange={(e) => setDraft({ ...draftRef.current, modelBaseUrl: e.target.value })}
                  onBlur={() => persist(draftRef.current)}
                  disabled={busy || provider === 'openrouter'}
                />
              </div>
              <div className="sf">
                <label htmlFor="s-key">API key</label>
                <input
                  id="s-key"
                  type="password"
                  value={keyText}
                  placeholder={
                    draft.keySource === 'file' || draft.keySet
                      ? 'Key stored — paste a new one to replace it'
                      : draft.keySource === 'env'
                        ? 'Environment key in use — paste a file key to override later'
                        : 'Paste an API key'
                  }
                  spellCheck={false}
                  autoCapitalize="none"
                  autoComplete="off"
                  onChange={(e) => setKeyText(e.target.value)}
                  disabled={busy}
                />
                <p className="fine">{keySourceMessage(draft.keySource, draft.keySet)}</p>
                <p className="fine">
                  <button type="button" onClick={() => commitKey(keyText)} disabled={busy || !keyText.trim()}>
                    Save key
                  </button>
                  {draft.keySource === 'file' || draft.keySet ? (
                    <button type="button" onClick={() => commitKey('')} disabled={busy}>
                      Clear key
                    </button>
                  ) : null}
                </p>
              </div>
              <div className="snc">
                <p className="fine">Model name and base URL are saved with the other settings.</p>
                <button type="button" onClick={runTest} disabled={busy}>
                  Test
                </button>
              </div>
            </section>
            <section className="sg" aria-labelledby="sh-hand">
              <h3 id="sh-hand">Babette&apos;s hand</h3>
              <p className="fine">How long the ink stays wet behind the pen. The same on every screen in the house.</p>
              <label className="wet-band" htmlFor="s-wet">
                Wet band
                <input
                  id="s-wet"
                  type="range"
                  min={0}
                  max={WET_BAND_MAX}
                  step={1}
                  value={draft.chatWetBand}
                  aria-valuemin={0}
                  aria-valuemax={WET_BAND_MAX}
                  aria-valuenow={draft.chatWetBand}
                  aria-valuetext={draft.chatWetBand === 0 ? 'plain' : String(draft.chatWetBand)}
                  onChange={(e) => setDraft({ ...draftRef.current, chatWetBand: Number(e.target.value) })}
                  onPointerUp={() => persist(draftRef.current)}
                  onKeyUp={() => persist(draftRef.current)}
                  onBlur={() => persist(draftRef.current)}
                  disabled={busy}
                />
                <span className="wet-band-val">{draft.chatWetBand === 0 ? 'plain' : draft.chatWetBand}</span>
              </label>
            </section>
            <section className={'sg plug' + (draft.inboxEnabled ? ' on' : '')} aria-labelledby="sh-inbox">
              <div className="plh">
                <div className="plt">
                  <h3 id="sh-inbox">Incoming recipes</h3>
                  <p className="fine">
                    Outside agents post recipes to a second listener. The only kitchen switch is on or off; the
                    sender needs the address and key.
                  </p>
                </div>
                <label className="pltg">
                  <input
                    type="checkbox"
                    checked={draft.inboxEnabled !== false}
                    disabled={busy}
                    onChange={(event) => {
                      setInboxSecret('')
                      patch({ inboxEnabled: event.target.checked })
                    }}
                  />{' '}
                  <span className="pls">{draft.inboxEnabled !== false ? 'On' : 'Off'}</span>
                </label>
              </div>
              <div className="plb">
                <div className="sf">
                  <label htmlFor="s-inbox-addr">Listener address</label>
                  <input
                    id="s-inbox-addr"
                    value={draft.inboxAddress || ''}
                    readOnly
                    spellCheck={false}
                    autoCapitalize="none"
                    autoComplete="off"
                  />
                  <p className="fine">
                    Binds with the kitchen host. Nothing is public until the host exposes this port. See
                    docs/incoming-recipes.md.
                  </p>
                </div>
                <p className="fine">
                  <button type="button" onClick={mintInboxKey} disabled={busy}>
                    New key
                  </button>
                  {draft.inboxKeySet ? ' A key is set; only its hash is stored.' : ' No key yet — mint one for agents.'}
                </p>
                {inboxSecret ? (
                  <div className="sf">
                    <label htmlFor="s-inbox-secret">Agent copy block (shown once)</label>
                    <textarea
                      id="s-inbox-secret"
                      value={inboxSecret}
                      readOnly
                      rows={10}
                      spellCheck={false}
                      autoCapitalize="none"
                      autoComplete="off"
                    />
                  </div>
                ) : null}
              </div>
            </section>
          </div>
        )}
        {tab === 'context' && (
          <div role="tabpanel" id="sp-context" aria-labelledby="st-context">
            <section className="sg" aria-labelledby="sh-house">
              <h3 id="sh-house">Household</h3>
              <div className="sf">
                <label htmlFor="s-family">Table name</label>
                <p className="fine">Shown wherever the app names itself.</p>
                <input
                  id="s-family"
                  value={draft.tableName}
                  maxLength={80}
                  placeholder="Babette's Table"
                  onChange={(e) => setDraft({ ...draftRef.current, tableName: e.target.value })}
                  onBlur={() => persist(draftRef.current)}
                  disabled={busy}
                />
              </div>
              <div className="sf">
                <label htmlFor="s-weather">Weather location</label>
                <input
                  id="s-weather"
                  value={draft.weatherLocation}
                  maxLength={120}
                  placeholder="City or postal code"
                  onChange={(e) => setDraft({ ...draftRef.current, weatherLocation: e.target.value })}
                  onBlur={() => persist(draftRef.current)}
                  disabled={busy}
                />
              </div>
              <p className="fine" style={{ marginTop: 6 }}>
                The forecast follows this location; the household time zone comes with it. Dinner hour and each
                night&apos;s tattva live on the Dinner tattva plugin.
              </p>
              <div className="sf">
                <label htmlFor="s-wk">Week starts on</label>
                <select
                  id="s-wk"
                  value={draft.weekStart}
                  onChange={(e) => patch({ weekStart: e.target.value })}
                  disabled={busy}
                >
                  {WEEK_STARTS.map((day) => (
                    <option key={day.value} value={day.value}>
                      {day.label}
                    </option>
                  ))}
                </select>
              </div>
            </section>
            <section className="sg" aria-labelledby="sh-ctx">
              <h3 id="sh-ctx">Household context</h3>
              <p className="fine">Included when a new chat starts. Edit each section separately.</p>
              {CONTEXT_LANES.map((lane) => {
                const row = lanes[lane.key]
                const isEditing = editing === lane.key
                return (
                  <div key={lane.key} className={'cx' + (isEditing ? ' editing' : '')}>
                    <h4>{lane.label}</h4>
                    {!isEditing && <i>{lanePreview(row?.text)}</i>}
                    {!isEditing && (
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(lane.key)
                          setEditText(row?.text || '')
                        }}
                      >
                        Edit
                      </button>
                    )}
                    {isEditing && (
                      <>
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          aria-label={lane.label}
                          disabled={busy}
                        />
                        <button type="button" onClick={() => setEditing(null)} disabled={busy}>
                          Cancel
                        </button>
                        <button type="button" onClick={() => commitLane(lane.key)} disabled={busy}>
                          Save
                        </button>
                      </>
                    )}
                  </div>
                )
              })}
            </section>
          </div>
        )}
        {tab === 'plugins' && (
          <div role="tabpanel" id="sp-plugins" aria-labelledby="st-plugins">
            {plugins.status !== 'ok' && (
              <p className="phint">
                {plugins.status === 'missing'
                  ? 'Plugin settings API is not on this kitchen yet.'
                  : plugins.status === 'loading'
                    ? 'Loading plugins…'
                    : 'Could not load plugins.'}
              </p>
            )}
            <p className="fine plg-intro">
              Babette&apos;s core stays small; extras plug in here. Each plugin can be switched off on its own.
            </p>
            {plugins.status === 'ok' &&
              plugins.plugins.map((plug) => (
                <PluginPanel
                  key={plug.id}
                  plugin={plug}
                  onUpdated={(next) =>
                    setPlugins((current) => ({
                      ...current,
                      plugins: current.plugins.map((item) => (item.id === next.id ? next : item)),
                    }))
                  }
                />
              ))}
          </div>
        )}
      </div>
      <div className="sbf">
        <label>
          <input
            type="checkbox"
            checked={motionOn}
            onChange={(e) => {
              const on = e.target.checked
              setMotionOn(on)
              setMotionLocal(on)
            }}
          />{' '}
          Motion
        </label>
        <span className="sp" />
        <small>
          Shared settings · <kbd>Esc</kbd> or <kbd>,</kbd> closes
        </small>
      </div>
    </div>
  )
}
