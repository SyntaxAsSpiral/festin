// Festin is served over plain HTTP on the home network, where browsers withhold
// the secure-context APIs (crypto.randomUUID, navigator.clipboard). These helpers
// use them when present and fall back to what plain HTTP allows.

export function newId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // A version 4 UUID from getRandomValues, which works in any context.
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const hex = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  // The older copy command still works without a secure context.
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.append(area)
  area.select()
  try {
    if (!document.execCommand('copy')) throw new Error('Copy was refused.')
  } finally {
    area.remove()
  }
}
