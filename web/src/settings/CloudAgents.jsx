import { useEffect, useState } from 'react'
import { callPluginAction } from './api.js'
import { outboundDestinations } from './plugins.js'

const EMPTY = { name: '', url: '', auth_env: '' }

export function CloudAgents({ plugin, enabled, busy, setBusy, onUpdated, note, setNote }) {
  const view = outboundDestinations(plugin)
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState(EMPTY)
  const [add, setAdd] = useState(EMPTY)

  useEffect(() => {
    setEditing(null)
    setDraft(EMPTY)
    setAdd(EMPTY)
  }, [plugin])

  async function run(body) {
    setBusy(true)
    setNote('')
    const result = await callPluginAction(plugin.id, 'destinations', body)
    setBusy(false)
    if (!result.ok) {
      setNote(result.error)
      return null
    }
    setNote('Saved.')
    onUpdated?.({
      ...plugin,
      settings: {
        ...plugin.settings,
        defaultAgent: result.body?.default || '',
        destinations: result.body?.destinations || [],
      },
    })
    return result.body
  }

  return (
    <div className="cloud-agents">
      <p className="fine">
        Webhook destinations for a notebook list. Choose one default. Babette uses it when you do not name an agent.
        Auth env is a variable name; keep the secret in the kitchen environment.
      </p>
      <div className="cloud-agent-list">
        {!view.destinations.length && <p className="fine">No cloud agents yet.</p>}
        {view.destinations.map((row) =>
          editing === row.name ? (
            <div key={row.name} className="cloud-agent-row cloud-agent-editor">
              <div className="sfr c3">
                <div className="sf">
                  <label htmlFor={'ca-edit-name-' + row.name}>Name</label>
                  <input
                    id={'ca-edit-name-' + row.name}
                    value={draft.name}
                    disabled={busy || !enabled}
                    maxLength={80}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                  />
                </div>
                <div className="sf">
                  <label htmlFor={'ca-edit-url-' + row.name}>Webhook URL</label>
                  <input
                    id={'ca-edit-url-' + row.name}
                    value={draft.url}
                    disabled={busy || !enabled}
                    inputMode="url"
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
                  />
                </div>
                <div className="sf">
                  <label htmlFor={'ca-edit-auth-' + row.name}>Auth env</label>
                  <input
                    id={'ca-edit-auth-' + row.name}
                    value={draft.auth_env}
                    disabled={busy || !enabled}
                    placeholder="AUTH_ENV_NAME"
                    spellCheck={false}
                    autoCapitalize="off"
                    autoComplete="off"
                    onChange={(event) => setDraft((current) => ({ ...current, auth_env: event.target.value }))}
                  />
                </div>
              </div>
              <div className="cloud-agent-actions">
                <button
                  type="button"
                  className="s-save"
                  disabled={busy || !enabled}
                  onClick={async () => {
                    const body = await run({
                      op: 'edit',
                      name: row.name,
                      new_name: draft.name,
                      url: draft.url,
                      auth_env: draft.auth_env,
                    })
                    if (body) {
                      setEditing(null)
                      setDraft(EMPTY)
                    }
                  }}
                >
                  Save
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setEditing(null)
                    setDraft(EMPTY)
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div key={row.name} className="cloud-agent-row">
              <div className="cloud-agent-main">
                <input
                  type="radio"
                  name="cloud-agent-default"
                  checked={row.name === view.default}
                  disabled={busy || !enabled}
                  aria-label={'Default ' + row.name}
                  onChange={async () => {
                    await run({ op: 'default', name: row.name })
                  }}
                />
                <div>
                  <strong>{row.name}</strong>
                  <p className="cloud-agent-url fine">{row.url}</p>
                  <p className="fine">{row.auth_env ? 'Auth env: ' + row.auth_env : 'No auth env.'}</p>
                </div>
              </div>
              <div className="cloud-agent-actions">
                <button
                  type="button"
                  disabled={busy || !enabled}
                  onClick={() => {
                    setEditing(row.name)
                    setDraft({ name: row.name, url: row.url, auth_env: row.auth_env })
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="s-danger"
                  disabled={busy || !enabled}
                  onClick={async () => {
                    await run({ op: 'remove', name: row.name })
                  }}
                >
                  Remove
                </button>
              </div>
            </div>
          ),
        )}
      </div>
      <div className="cloud-agent-add">
        <div className="sfr c3">
          <div className="sf">
            <label htmlFor="ca-add-name">Name</label>
            <input
              id="ca-add-name"
              value={add.name}
              disabled={busy || !enabled}
              maxLength={80}
              placeholder="Agent name"
              spellCheck={false}
              autoComplete="off"
              onChange={(event) => setAdd((current) => ({ ...current, name: event.target.value }))}
            />
          </div>
          <div className="sf">
            <label htmlFor="ca-add-url">Webhook URL</label>
            <input
              id="ca-add-url"
              value={add.url}
              disabled={busy || !enabled}
              placeholder="https://example.invalid/babette"
              inputMode="url"
              spellCheck={false}
              autoComplete="off"
              onChange={(event) => setAdd((current) => ({ ...current, url: event.target.value }))}
            />
          </div>
          <div className="sf">
            <label htmlFor="ca-add-auth">Auth env</label>
            <input
              id="ca-add-auth"
              value={add.auth_env}
              disabled={busy || !enabled}
              placeholder="AUTH_ENV_NAME"
              spellCheck={false}
              autoCapitalize="off"
              autoComplete="off"
              onChange={(event) => setAdd((current) => ({ ...current, auth_env: event.target.value }))}
            />
          </div>
        </div>
        <div className="cloud-agent-actions">
          <button
            type="button"
            className="s-save"
            disabled={busy || !enabled}
            onClick={async () => {
              const body = await run({
                op: 'add',
                name: add.name,
                url: add.url,
                auth_env: add.auth_env,
              })
              if (body) setAdd(EMPTY)
            }}
          >
            Add destination
          </button>
        </div>
      </div>
      {note ? (
        <p className={'fine' + (note !== 'Saved.' ? ' mo' : '')} role="status">
          {note}
        </p>
      ) : null}
    </div>
  )
}
