/**
 * @vitest-environment happy-dom
 */
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { RecipePage } from './pages.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const formule = {
  id: 'CBK-0001',
  title: 'Custard',
  kind: 'formule',
  category: 'sweets',
  voice: 'Babette',
  ingredients: ['2 eggs, beaten'],
  method: 'Temper the yolks.',
  seeAlso: [
    { id: 'CBK-0490', title: 'Stainless Steel' },
    { id: 'CBK-0484', title: 'Fats' },
  ],
}

describe('See also on a formule card', () => {
  let root
  let host

  afterEach(() => {
    act(() => root?.unmount())
    host?.remove()
    root = null
    host = null
  })

  function render(recipe) {
    act(() => root?.unmount())
    host?.remove()
    host = document.createElement('div')
    document.body.appendChild(host)
    act(() => {
      root = createRoot(host)
      root.render(createElement(RecipePage, { recipe }))
    })
  }

  it('puts title links under the method', () => {
    render(formule)
    const line = host.querySelector('.see-also')
    const method = host.querySelector('.method')
    expect(method.nextElementSibling).toBe(line)
    expect(line.textContent).toBe('See also: Stainless Steel, Fats')
    const links = [...line.querySelectorAll('a')]
    expect(links.map((link) => link.textContent)).toEqual(['Stainless Steel', 'Fats'])
    expect(links[0].getAttribute('href')).toBe('/recipes/CBK-0490')
    expect(links[0].dataset.recipe).toBe('CBK-0490')
    expect(links[1].getAttribute('href')).toBe('/recipes/CBK-0484')
    expect(links[1].dataset.recipe).toBe('CBK-0484')
  })

  it('shows nothing when the list is empty or the card is a praxis', () => {
    render({ ...formule, seeAlso: [] })
    expect(host.querySelector('.see-also')).toBeNull()
    render({ ...formule, kind: 'praxis', appliesTo: ['egg'], seeAlso: formule.seeAlso })
    expect(host.querySelector('.see-also')).toBeNull()
    expect(host.querySelector('.form-mark').textContent).toBe('Praxis')
  })
})
