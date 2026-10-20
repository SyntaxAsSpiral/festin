/**
 * @vitest-environment happy-dom
 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { KitchenLogList } from './KitchenLog.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const NOW = new Date('2026-10-19T18:00:00.000Z')

function ev(fields) {
  return { id: 'x', title: 'Title', at: '2026-10-20T04:34:00.000Z', ...fields }
}

const ENTRIES = [
  ev({
    kind: 'recipe_cooked',
    id: 'zuni',
    title: 'Zuni Chicken & Bread Salad',
    category: 'chicken',
    at: '2026-10-20T03:00:00.000Z',
  }),
  ev({
    kind: 'recipe_cooked',
    id: 'zuni',
    title: 'Zuni Chicken & Bread Salad',
    category: 'chicken',
    at: '2026-10-20T02:00:00.000Z',
  }),
  ev({
    kind: 'recipe_cooked',
    id: 'zuni',
    title: 'Zuni Chicken & Bread Salad',
    category: 'chicken',
    at: '2026-10-20T01:00:00.000Z',
  }),
  ev({
    kind: 'recipe_edited',
    id: 'beans',
    title: "Bridget's Chicken Salad",
    category: 'salads-sides',
    at: '2026-10-20T00:30:00.000Z',
  }),
]

describe('LogFold', () => {
  let root
  let host

  afterEach(() => {
    act(() => root?.unmount())
    host?.remove()
    root = null
    host = null
  })

  async function render(onOpen) {
    host = document.createElement('div')
    document.body.appendChild(host)
    await act(async () => {
      root = createRoot(host)
      root.render(
        createElement(KitchenLogList, {
          entries: ENTRIES,
          timeZone: 'America/Los_Angeles',
          weekStart: 'sat',
          now: NOW,
          onOpen,
        }),
      )
    })
  }

  it('expands and collapses a fold in place from its button', async () => {
    const opened = []
    await render((kind, id) => opened.push([kind, id]))

    const toggle = host.querySelector('.tl-cooked button.tlk')
    const panel = host.querySelector('.tl-cooked .twb')
    expect(toggle.tagName).toBe('BUTTON')
    expect(toggle.getAttribute('type')).toBe('button')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(toggle.textContent).toContain('3× · Zuni Chicken & Bread Salad')
    expect(panel.hidden).toBe(true)
    expect(host.querySelector('.tl-cooked img')).toBeTruthy()

    await act(async () => {
      toggle.click()
    })
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(panel.hidden).toBe(false)
    const inner = panel.querySelectorAll('button')
    expect(inner).toHaveLength(3)

    await act(async () => {
      inner[0].click()
    })
    expect(opened).toEqual([['recipe_cooked', 'zuni']])
    expect(toggle.getAttribute('aria-expanded')).toBe('true')

    await act(async () => {
      toggle.click()
    })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(panel.hidden).toBe(true)
  })

  it('draws a routine row as one quiet line without a thumbnail', async () => {
    await render(() => {})
    const quiet = host.querySelector('li.tl-quiet')
    expect(quiet).toBeTruthy()
    expect(quiet.className).toContain('tl-r')
    expect(quiet.querySelector('img')).toBeNull()
    expect(quiet.textContent).toContain('Recipe updated')
    expect(quiet.textContent).toContain("Bridget's Chicken Salad")
    const key = host.querySelector('li.tl-cooked')
    expect(key.className).not.toContain('tl-quiet')
    expect(key.querySelector('img')).toBeTruthy()
  })
})