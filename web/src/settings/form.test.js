import { describe, expect, it } from 'vitest'
import {
  OPENROUTER_BASE,
  baseUrlForProvider,
  draftFromSettings,
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
      dinnerHour: '18:00',
      weekStart: 'mon',
      weather: { location: '83835', timezone: 'America/Los_Angeles' },
      updatedAt: '2026-10-18T12:00:00.000000Z',
    })
    expect(draft).toMatchObject({
      tableName: 'Holliday Table',
      dinnerHour: '18:00',
      weekStart: 'mon',
      weatherLocation: '83835',
      updatedAt: '2026-10-18T12:00:00.000000Z',
      modelBaseUrl: OPENROUTER_BASE,
      modelName: '',
    })
  })

  it('reads the nested model object without treating it as the name', () => {
    const draft = draftFromSettings({
      tableName: "Babette's Table",
      model: {
        baseUrl: 'http://127.0.0.1:1234/v1',
        name: 'qwen2.5-7b-instruct',
        keySet: true,
      },
    })
    expect(draft.modelName).toBe('qwen2.5-7b-instruct')
    expect(draft.modelBaseUrl).toBe('http://127.0.0.1:1234/v1')
    expect(draft.keySet).toBe(true)
    expect(providerOf(draft.modelBaseUrl)).toBe('local')
  })

  it('keeps flat model fields when a caller still sends them', () => {
    const draft = draftFromSettings({
      tableName: "Babette's Table",
      dinnerHour: '17:30',
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
        dinnerHour: '18:15',
        weekStart: 'sun',
        weatherLocation: '83835',
        modelName: 'tool-model',
        modelBaseUrl: OPENROUTER_BASE,
      },
      'stamp-1',
    )
    expect(body).toEqual({
      tableName: 'Holliday Table',
      dinnerHour: '18:15',
      weekStart: 'sun',
      weatherLocation: '83835',
      modelName: 'tool-model',
      modelBaseUrl: OPENROUTER_BASE,
      expectedUpdatedAt: 'stamp-1',
      expected_updated_at: 'stamp-1',
    })
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
    expect(readSaveResult(400, { error: 'Use a dinner hour like 17:30.' })).toMatchObject({
      ok: false,
      conflict: false,
      error: 'Use a dinner hour like 17:30.',
    })
  })
})
