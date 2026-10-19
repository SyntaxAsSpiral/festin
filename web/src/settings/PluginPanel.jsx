import { useEffect, useRef, useState } from 'react'
import { toastForPrintResult } from '../meals/printToast.js'
import { CloudAgents } from './CloudAgents.jsx'
import { callPluginAction, putPlugin } from './api.js'
import { draftFromPlugin, fieldsFromSchema, pluginIcon, pluginSaveBody, pluginTestAction } from './plugins.js'

export function PluginPanel({ plugin, onUpdated }) {
  const [{ enabled, draft, secrets }, setLocal] = useState(() => draftFromPlugin(plugin))
  const [dirtySecrets, setDirtySecrets] = useState({})
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const draftRef = useRef(draft)
  const secretsRef = useRef(secrets)
  const dirtyRef = useRef(dirtySecrets)
  const enabledRef = useRef(enabled)

  useEffect(() => {
    const next = draftFromPlugin(plugin)
    setLocal(next)
    setDirtySecrets({})
    setNote('')
    draftRef.current = next.draft
    secretsRef.current = next.secrets
    dirtyRef.current = {}
    enabledRef.current = next.enabled
  }, [plugin])

  const fields =
    plugin.id === 'outbound'
      ? []
      : fieldsFromSchema(plugin.schema).filter((field) => field.key !== 'defaultAgent')
  const testAction = pluginTestAction(plugin)

  async function save(partial) {
    const nextEnabled = partial.enabled ?? enabledRef.current
    const nextDraft = partial.draft ?? draftRef.current
    const nextDirty = partial.dirtySecrets ?? dirtyRef.current
    const body = pluginSaveBody({
      enabled: nextEnabled,
      draft: nextDraft,
      secrets: secretsRef.current,
      dirtySecrets: nextDirty,
    })
    if (!('enabled' in body) && !body.settings) return
    setBusy(true)
    setNote('')
    const result = await putPlugin(plugin.id, body)
    setBusy(false)
    if (!result.ok) {
      setNote(result.error)
      return
    }
    const fresh = draftFromPlugin(result.body)
    setLocal(fresh)
    setDirtySecrets({})
    draftRef.current = fresh.draft
    secretsRef.current = fresh.secrets
    dirtyRef.current = {}
    enabledRef.current = fresh.enabled
    setNote('Saved.')
    onUpdated?.(result.body)
  }

  function setField(key, value, { secret } = {}) {
    const nextDraft = { ...draftRef.current, [key]: value }
    draftRef.current = nextDraft
    setLocal((current) => ({ ...current, draft: nextDraft }))
    if (secret) {
      const nextDirty = { ...dirtyRef.current, [key]: true }
      dirtyRef.current = nextDirty
      setDirtySecrets(nextDirty)
    }
  }

  return (
    <section className={'sg plug' + (enabled ? ' on' : '')} aria-labelledby={'sh-' + plugin.id}>
      <div className="plh">
        <span className="plic" aria-hidden="true">
          {pluginIcon(plugin)}
        </span>
        <div className="plt">
          <h3 id={'sh-' + plugin.id}>{plugin.name || plugin.id}</h3>
          {plugin.id === 'printer' && (
            <p className="fine">Prints the weekly slip, recipe cards and shopping lists on a receipt printer.</p>
          )}
          {plugin.id === 'tattva' && (
            <p className="fine">
              Names the element at the dinner hour for planning and colours each week in the Kitchen Log.
            </p>
          )}
          {plugin.id === 'outbound' && (
            <p className="fine">Send a notebook list to a named webhook when the cook asks.</p>
          )}
        </div>
        <label className="pltg">
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={(event) => {
              const next = event.target.checked
              enabledRef.current = next
              setLocal((current) => ({ ...current, enabled: next }))
              void save({ enabled: next })
            }}
          />{' '}
          <span className="pls">{enabled ? 'On' : 'Off'}</span>
        </label>
      </div>
      <div className="plb">
        {fields.map((field) => (
          <div key={field.key} className="sf">
            <label htmlFor={'p-' + plugin.id + '-' + field.key}>{field.label}</label>
            {field.type === 'enum' && (
              <select
                id={'p-' + plugin.id + '-' + field.key}
                value={draft[field.key] ?? ''}
                disabled={busy || !enabled}
                onChange={(event) => {
                  setField(field.key, event.target.value)
                  void save({ draft: { ...draftRef.current, [field.key]: event.target.value } })
                }}
              >
                {field.options.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            )}
            {field.type === 'boolean' && (
              <label className="pck2">
                <input
                  type="checkbox"
                  checked={Boolean(draft[field.key])}
                  disabled={busy || !enabled}
                  onChange={(event) => {
                    setField(field.key, event.target.checked)
                    void save({ draft: { ...draftRef.current, [field.key]: event.target.checked } })
                  }}
                />{' '}
                {field.label}
              </label>
            )}
            {field.type === 'number' && (
              <input
                id={'p-' + plugin.id + '-' + field.key}
                type="number"
                value={draft[field.key] ?? ''}
                disabled={busy || !enabled}
                onChange={(event) => setField(field.key, event.target.value === '' ? '' : Number(event.target.value))}
                onBlur={() => save({ draft: draftRef.current })}
              />
            )}
            {field.type === 'secret' && (
              <>
                <input
                  id={'p-' + plugin.id + '-' + field.key}
                  type="password"
                  value={draft[field.key] ?? ''}
                  placeholder={secrets[field.key] === 'set' ? 'set — type to replace' : 'not set'}
                  autoComplete="off"
                  spellCheck={false}
                  disabled={busy || !enabled}
                  onChange={(event) => setField(field.key, event.target.value, { secret: true })}
                  onBlur={() => {
                    if (dirtyRef.current[field.key] && String(draftRef.current[field.key] || '').length)
                      void save({ draft: draftRef.current, dirtySecrets: dirtyRef.current })
                  }}
                />
                <p className="fine">
                  {secrets[field.key] === 'set' ? 'Token is set on the kitchen.' : 'Token is not set.'} The value is
                  never shown again.
                </p>
              </>
            )}
            {(field.type === 'string' || (!['enum', 'boolean', 'number', 'secret'].includes(field.type))) && (
              <input
                id={'p-' + plugin.id + '-' + field.key}
                type={field.key === 'dinnerHour' || field.input === 'time' ? 'time' : 'text'}
                step={field.key === 'dinnerHour' || field.input === 'time' ? 900 : undefined}
                value={draft[field.key] ?? ''}
                disabled={busy || !enabled}
                spellCheck={false}
                autoCapitalize="none"
                autoComplete="off"
                onChange={(event) => setField(field.key, event.target.value)}
                onBlur={() => save({ draft: draftRef.current })}
              />
            )}
            {field.help ? <p className="fine">{field.help}</p> : null}
          </div>
        ))}
        {plugin.id === 'printer' && (
          <div className="snc">
            <p className={'fine' + (note && note !== 'Saved.' ? ' mo' : '')} id={'p-note-' + plugin.id}>
              {note || (testAction ? 'Ready to print a test slip.' : 'No test action on this plugin yet.')}
            </p>
            <button
              type="button"
              id={'p-test-' + plugin.id}
              disabled={!enabled || busy || !testAction}
              title={testAction ? 'Print a test slip' : 'No test action on the printer plugin'}
              onClick={async () => {
                if (!testAction) return
                setBusy(true)
                setNote('Sending the test slip…')
                const result = await callPluginAction(plugin.id, testAction, {})
                setBusy(false)
                setNote(toastForPrintResult(result))
              }}
            >
              Print test slip
            </button>
          </div>
        )}
        {plugin.id === 'outbound' && (
          <CloudAgents
            plugin={plugin}
            enabled={enabled}
            busy={busy}
            setBusy={setBusy}
            onUpdated={onUpdated}
            note={note}
            setNote={setNote}
          />
        )}
        {plugin.id !== 'printer' && plugin.id !== 'outbound' && note && (
          <p className={'fine' + (note !== 'Saved.' ? ' mo' : '')} role="status">
            {note}
          </p>
        )}
      </div>
    </section>
  )
}
