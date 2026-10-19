import { describe, expect, it } from 'vitest'
import {
  draftFromPlugin,
  fieldFromSchema,
  fieldsFromSchema,
  isSecretField,
  pluginSaveBody,
  pluginTestAction,
  readPluginSaveResult,
  secretIsSet,
  secretState,
} from './plugins.js'

const printerSchema = [
  { key: 'receiverUrl', type: 'string', default: '', label: 'Print receiver URL' },
  { key: 'token', type: 'string', default: '', label: 'Print receiver token', secret: true },
  {
    key: 'band',
    type: 'string',
    default: 'scroll',
    label: 'Band art',
    enum: ['scroll', 'rose'],
    choices: [
      { id: 'scroll', file: 'scroll.png', description: 'A quiet scroll' },
      { id: 'rose', file: 'rose.png', description: 'A small rose' },
    ],
  },
]

describe('plugin schema mapping', () => {
  it('maps string, enum, and token fields', () => {
    const fields = fieldsFromSchema(printerSchema)
    expect(fields).toHaveLength(3)
    expect(fields[0]).toMatchObject({ key: 'receiverUrl', type: 'string', secret: false })
    expect(fields[1]).toMatchObject({ key: 'token', type: 'secret', secret: true })
    expect(fields[2]).toMatchObject({
      key: 'band',
      type: 'enum',
      options: [
        { value: 'scroll', label: 'A quiet scroll' },
        { value: 'rose', label: 'A small rose' },
      ],
    })
  })

  it('treats boolean and number types when a later plugin uses them', () => {
    expect(fieldFromSchema({ key: 'auto', type: 'boolean', default: false, label: 'Auto' })).toMatchObject({
      type: 'boolean',
      secret: false,
    })
    expect(fieldFromSchema({ key: 'port', type: 'number', default: 9100, label: 'Port' })).toMatchObject({
      type: 'number',
    })
    expect(isSecretField({ key: 'apiKey', type: 'string' })).toBe(true)
    expect(secretState('abc')).toBe('set')
    expect(secretState('')).toBe('not set')
  })

  it('builds a local draft that never echoes a token value', () => {
    const { enabled, draft, secrets } = draftFromPlugin({
      id: 'printer',
      enabled: true,
      settings: { receiverUrl: 'http://127.0.0.1:9', tokenSet: true, band: 'rose' },
      schema: printerSchema,
    })
    expect(enabled).toBe(true)
    expect(draft).toEqual({ receiverUrl: 'http://127.0.0.1:9', token: '', band: 'rose' })
    expect(secrets).toEqual({ token: 'set' })
    expect(secretIsSet({ tokenSet: true }, 'token')).toBe(true)
    expect(secretIsSet({ tokenSet: false }, 'token')).toBe(false)
  })

  it('omits untouched secrets from the PUT body', () => {
    expect(
      pluginSaveBody({
        enabled: true,
        draft: { receiverUrl: 'http://127.0.0.1:9', token: '', band: 'scroll' },
        secrets: { token: 'set' },
        dirtySecrets: {},
      }),
    ).toEqual({
      enabled: true,
      settings: { receiverUrl: 'http://127.0.0.1:9', band: 'scroll' },
    })
    expect(
      pluginSaveBody({
        draft: { receiverUrl: 'http://127.0.0.1:9', token: 'new-token', band: 'scroll' },
        secrets: { token: 'set' },
        dirtySecrets: { token: true },
      }),
    ).toEqual({
      settings: { receiverUrl: 'http://127.0.0.1:9', token: 'new-token', band: 'scroll' },
    })
  })
})

describe('plugin save result', () => {
  it('surfaces 400 and 409 inline', () => {
    expect(readPluginSaveResult(400, { error: 'Print receiver URL must be an http(s) URL.' })).toMatchObject({
      ok: false,
      conflict: false,
      error: 'Print receiver URL must be an http(s) URL.',
    })
    expect(readPluginSaveResult(409, { error: 'Plugin settings changed.' })).toMatchObject({
      ok: false,
      conflict: true,
      error: 'Plugin settings changed.',
    })
    expect(readPluginSaveResult(200, { id: 'printer', enabled: true })).toMatchObject({ ok: true })
  })

  it('wires the printer test-slip action for the Settings button', () => {
    expect(pluginTestAction({ id: 'printer', name: 'Thermal printer' })).toBe('test-slip')
    expect(pluginTestAction({ id: 'hue' })).toBe(null)
  })
})
