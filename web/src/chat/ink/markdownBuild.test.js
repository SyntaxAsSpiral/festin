/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it, vi } from 'vitest'
import { createInkBuilder } from './markdownBuild.js'

describe('incremental markdown builder', () => {
  it('wraps each typed character in a reusable span', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('Hi')
    const spans = host.querySelectorAll('.ink-c')
    expect([...spans].map((s) => s.textContent).join('')).toBe('Hi')
    expect(spans).toHaveLength(2)
  })

  it('reuses the same span nodes when more text arrives so animations keep running', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('Ab')
    const first = host.querySelectorAll('.ink-c')[0]
    first.classList.add('on')
    first.dataset.mark = 'keep'
    b.setTyped('Abc')
    const again = host.querySelectorAll('.ink-c')
    expect(again[0]).toBe(first)
    expect(again[0].dataset.mark).toBe('keep')
    expect(again[0].classList.contains('on')).toBe(true)
    expect(again).toHaveLength(3)
  })

  it('builds paragraphs, lists and bold from Markdown', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('Hello\n\n- **Leeks**\n- then stock')
    expect(host.querySelectorAll('p').length).toBeGreaterThanOrEqual(1)
    expect(host.querySelector('strong')).toBeTruthy()
    expect(host.querySelector('li')).toBeTruthy()
    const text = [...host.querySelectorAll('.ink-c')].map((s) => s.textContent).join('')
    expect(text.replace(/\s+/g, ' ')).toContain('Leeks')
    expect(text).toContain('stock')
  })

  it('lights a character by index and returns its element', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('xy')
    const el = b.light(0, { durationMs: 360, mx: '0.5em', my: '1em' })
    expect(el.classList.contains('on')).toBe(true)
    expect(el.style.getPropertyValue('--d')).toBe('360ms')
    expect(el.style.getPropertyValue('--mx')).toBe('0.5em')
  })

  it('clears on reset and shrinks when the typed prefix shortens', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('abcdef')
    expect(b.length).toBe(6)
    b.setTyped('')
    expect(b.length).toBe(0)
    expect(host.querySelectorAll('.ink-c')).toHaveLength(0)
  })

  it('appends plain growth into the last paragraph without dropping earlier spans', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    b.setTyped('Stock')
    const first = host.querySelector('.ink-c')
    first.dataset.mark = 'keep'
    b.setTyped('Stock pot')
    expect(host.querySelector('.ink-c').dataset.mark).toBe('keep')
    expect([...host.querySelectorAll('.ink-c')].map((s) => s.textContent).join('')).toBe('Stock pot')
  })
})

describe('a rebuild does not restart lit letters', () => {
  it('keeps earlier letters mounted when a new paragraph opens', () => {
    const now = vi.spyOn(performance, 'now')
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    now.mockReturnValue(1000)
    b.setTyped('Bread')
    for (let i = 0; i < b.length; i++) b.light(i, { durationMs: 360 })
    const first = host.querySelector('.ink-c')
    now.mockReturnValue(1500)
    b.setTyped('Bread\n\nRise')
    expect(host.querySelector('.ink-c')).toBe(first)
    expect(first.textContent).toBe('B')
    expect(first.classList.contains('on')).toBe(true)
    expect(host.textContent).toContain('Rise')
    now.mockRestore()
  })

  it('resumes a lit letter at its age when its own line is rebuilt', () => {
    const now = vi.spyOn(performance, 'now')
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    now.mockReturnValue(1000)
    b.setTyped('**Hi')
    for (let i = 0; i < b.length; i++) b.light(i, { durationMs: 360 })
    const first = host.querySelector('.ink-c')
    now.mockReturnValue(1500)
    b.setTyped('**Hi**')
    const again = host.querySelector('.ink-c')
    expect(again).toBe(first)
    expect(again.textContent).toBe('H')
    expect(again.style.animationDelay).toBe('-500ms')
    now.mockRestore()
  })

  it('keeps the first list item when the next one is written', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    const src = 'Intro line.\n\n- **Leeks** and stock\n- then more'
    b.setTyped(src.slice(0, 24))
    const first = host.querySelector('.ink-c')
    first.dataset.mark = 'keep'
    for (let i = 25; i <= src.length; i++) b.setTyped(src.slice(0, i))
    expect(host.querySelector('.ink-c')).toBe(first)
    expect(first.dataset.mark).toBe('keep')
    expect(host.querySelectorAll('li')).toHaveLength(2)
    expect(host.textContent).toContain('then more')
  })

  it('keeps the line above a soft break when a card link closes', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    const src = 'Backbone:\n[Stock](CBK-0479) next'
    for (let i = 1; i <= src.length; i++) b.setTyped(src.slice(0, i))
    expect(host.textContent).toContain('Backbone:')
    expect(host.querySelector('br')).not.toBeNull()
    const link = host.querySelector('a[data-recipe="CBK-0479"]')
    expect(link).not.toBeNull()
    expect(link.textContent).toBe('Stock')
    expect(link.textContent).not.toContain('next')
    expect(host.textContent).toContain('next')
  })

  it('leaves words after a card link outside the link', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    const src = 'See [Cake](CBK-0001) please'
    for (let i = 1; i <= src.length; i++) b.setTyped(src.slice(0, i))
    const link = host.querySelector('a[data-recipe="CBK-0001"]')
    expect(link).not.toBeNull()
    expect(link.textContent).toBe('Cake')
    expect(host.textContent).toContain('please')
    expect(link.textContent).not.toContain('please')
  })

  it('finishes a card link typed letter by letter, even as the last thing written', () => {
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    const src = 'Try [Raw Apple Cake](CBK-0605)'
    for (let i = 1; i <= src.length; i++) b.setTyped(src.slice(0, i))
    const link = host.querySelector('a[data-recipe="CBK-0605"]')
    expect(link).not.toBeNull()
    expect(link.textContent).toBe('Raw Apple Cake')
    expect(host.textContent).not.toContain('CBK-0605')
    expect(host.textContent).not.toContain('[')
  })
})
