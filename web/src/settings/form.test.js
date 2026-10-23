import { describe, expect, it } from 'vitest'
import {
  OPENROUTER_BASE,
  baseUrlForProvider,
  draftFromSettings,
  inboxKeyBlock,
  lanePreview,
  parseSettingsTab,
  providerOf,
  readSaveResult,
  settingsSaveBody,
} from './form.js'

describe('settings form mapping', () => {
  it('reads the public settings shape into a draft', () => {
    const draft = draftFromSettings({
      tableName: 'Holliday Table',
      weekStart: 'mon',
      weather: { location: '83835', timezone: 'America/Los_Angeles' },
      updatedAt: '2026-10-18T12:00:00.000000Z',
    })
    expect(draft).toMatchObject({
      tableName: 'Holliday Table',
      weekStart: 'mon',
      weatherLocation: '83835',
      updatedAt: '2026-10-18T12:00:00.000000Z',
      modelBaseUrl: OPENROUTER_BASE,
      modelName: '',
    })
    expect(draft).not.toHaveProperty('dinnerHour')
  })

  it('reads the nested model object without treating it as the name', () => {
    const draft = draftFromSettings({
      tableName: "Babette's Table",
      model: {
        baseUrl: 'http://127.0.0.1:1234/v1',
        name: 'qwen2.5-7b-instruct',
        keySet: true,
        keySource: 'file',
      },
    })
    expect(draft.modelName).toBe('qwen2.5-7b-instruct')
    expect(draft.modelBaseUrl).toBe('http://127.0.0.1:1234/v1')
    expect(draft.keySet).toBe(true)
    expect(draft.keySource).toBe('file')
    expect(providerOf(draft.modelBaseUrl)).toBe('local')
  })

  it('names an environment key without claiming a file is stored', () => {
    const draft = draftFromSettings({
      model: { baseUrl: OPENROUTER_BASE, name: '', keySet: false, keySource: 'env' },
    })
    expect(draft.keySource).toBe('env')
    expect(draft.keySet).toBe(false)
  })

  it('keeps flat model fields when a caller still sends them', () => {
    const draft = draftFromSettings({
      tableName: "Babette's Table",
      weekStart: 'sat',
      weather: { location: '' },
      modelName: 'qwen2.5-7b-instruct',
      modelBaseUrl: 'http://127.0.0.1:1234/v1',
      updatedAt: 't1',
    })
    expect(draft.modelName).toBe('qwen2.5-7b-instruct')
    expect(draft.modelBaseUrl).toBe('http://127.0.0.1:1234/v1')
    expect(providerOf(draft.modelBaseUrl)).toBe('local')
  })

  it('builds the POST body with expectedUpdatedAt for the conflict guard', () => {
    const body = settingsSaveBody(
      {
        tableName: 'Holliday Table',
        weekStart: 'sun',
        weatherLocation: '83835',
        modelName: 'tool-model',
        modelBaseUrl: OPENROUTER_BASE,
      },
      'stamp-1',
    )
    expect(body).toEqual({
      tableName: 'Holliday Table',
      weekStart: 'sun',
      weatherLocation: '83835',
      modelName: 'tool-model',
      modelBaseUrl: OPENROUTER_BASE,
      inboxEnabled: true,
      chatWetBand: 45,
      expectedUpdatedAt: 'stamp-1',
      expected_updated_at: 'stamp-1',
    })
    expect(body).not.toHaveProperty('dinnerHour')
  })

  it('reads inbox settings and builds the one-time agent copy block', () => {
    const draft = draftFromSettings({
      inbox: { enabled: true, address: 'http://127.0.0.1:8896', keySet: true },
    })
    expect(draft.inboxEnabled).toBe(true)
    expect(draft.inboxAddress).toBe('http://127.0.0.1:8896')
    expect(draft.inboxKeySet).toBe(true)
    expect(draft.chatWetBand).toBe(45)
    expect(draftFromSettings({ chatWetBand: 0 }).chatWetBand).toBe(0)
    expect(settingsSaveBody({ ...draft, chatWetBand: 33 }).chatWetBand).toBe(33)
    expect(settingsSaveBody({ ...draft, inboxEnabled: false }).inboxEnabled).toBe(false)
    const block = inboxKeyBlock({
      key: 'secret-once',
      address: 'http://127.0.0.1:8896',
      exampleCurl: 'curl example',
    })
    expect(block).toContain('URL: http://127.0.0.1:8896')
    expect(block).toContain('Key: secret-once')
    expect(block).toContain('curl example')
  })

  it('switches the base URL when the connection provider changes', () => {
    expect(baseUrlForProvider('openrouter', 'http://127.0.0.1:1234/v1')).toBe(OPENROUTER_BASE)
    expect(baseUrlForProvider('local', OPENROUTER_BASE)).toBe('')
    expect(baseUrlForProvider('local', 'http://127.0.0.1:1234/v1')).toBe('http://127.0.0.1:1234/v1')
    expect(providerOf(OPENROUTER_BASE)).toBe('openrouter')
  })

  it('parses the settings URL tab and previews context lanes', () => {
    expect(parseSettingsTab('model')).toBe('model')
    expect(parseSettingsTab('CONTEXT')).toBe('context')
    expect(parseSettingsTab('nope')).toBe(null)
    expect(lanePreview('')).toBe('Not set')
    expect(lanePreview('Three at the table.\nMore later.')).toBe('Three at the table.')
  })
})

describe('settings conflict path', () => {
  it('marks a 409 as a conflict with the server message', () => {
    expect(readSaveResult(409, { error: 'Settings changed. Refresh before saving.' })).toEqual({
      ok: false,
      conflict: true,
      error: 'Settings changed. Refresh before saving.',
      body: { error: 'Settings changed. Refresh before saving.' },
    })
  })

  it('accepts a 200 body and surfaces other errors', () => {
    expect(readSaveResult(200, { tableName: "Babette's Table", updatedAt: 't2' })).toMatchObject({
      ok: true,
      conflict: false,
      body: { tableName: "Babette's Table", updatedAt: 't2' },
    })
    expect(readSaveResult(400, { error: 'Enter a table name under 80 characters.' })).toMatchObject({
      ok: false,
      conflict: false,
      error: 'Enter a table name under 80 characters.',
    })
  })
})
