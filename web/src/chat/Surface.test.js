import { describe, expect, it } from 'vitest'
import { drawerSnaps, openedState } from './Surface.jsx'

describe('chat drawer', () => {
  it('opens Full on a phone and Peek on a tablet', () => {
    expect(openedState(true)).toBe('full')
    expect(openedState(false)).toBe('peek')
  })

  it('snaps when the viewport moves under it, so a closing keyboard cannot pull it down', () => {
    expect(drawerSnaps({ dragging: false, viewportMoved: true, keyboard: 0, reduced: false })).toBe(true)
  })

  it('snaps while the keyboard is up, while dragging, and under reduced motion', () => {
    expect(drawerSnaps({ dragging: false, viewportMoved: false, keyboard: 300, reduced: false })).toBe(true)
    expect(drawerSnaps({ dragging: true, viewportMoved: false, keyboard: 0, reduced: false })).toBe(true)
    expect(drawerSnaps({ dragging: false, viewportMoved: false, keyboard: 0, reduced: true })).toBe(true)
  })

  it('animates a plain open or close', () => {
    expect(drawerSnaps({ dragging: false, viewportMoved: false, keyboard: 0, reduced: false })).toBe(false)
  })
})
