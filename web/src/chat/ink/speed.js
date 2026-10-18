import { SPEED_KEY, clampCps, DEFAULT_TYPE_CPS } from './constants.js'

export function readWritingSpeed() {
  try {
    const raw = localStorage.getItem(SPEED_KEY)
    if (raw == null || raw === '') return DEFAULT_TYPE_CPS
    return clampCps(raw)
  } catch {
    return DEFAULT_TYPE_CPS
  }
}

export function writeWritingSpeed(cps) {
  const value = clampCps(cps)
  try {
    localStorage.setItem(SPEED_KEY, String(value))
  } catch {
    /* private mode */
  }
  window.dispatchEvent(new CustomEvent('festin-writing-speed', { detail: value }))
  return value
}
