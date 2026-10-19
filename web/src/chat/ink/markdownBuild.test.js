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
  it('lets each lit letter resume at its own age after a Markdown boundary', () => {
    const now = vi.spyOn(performance, 'now')
    const host = document.createElement('div')
    const b = createInkBuilder(host)
    now.mockReturnValue(1000)
    b.setTyped('Bread')
    for (let i = 0; i < b.length; i++) b.light(i, { durationMs: 360 })
    now.mockReturnValue(1500)
    // A new paragraph is a structural change: the builder rebuilds the tree.
    b.setTyped('Bread\n\nRise')
    const first = host.querySelector('.ink-c')
    expect(first.textContent).toBe('B')
    expect(first.style.animationDelay).toBe('-500ms')
    now.mockRestore()
  })
})
