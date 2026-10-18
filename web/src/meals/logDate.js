// Kitchen Log date lines. Approximate chat dates are a week anchor (date_approx), not a clock.

export function formatLogWhen(iso, { approx = false } = {}) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10)
  if (approx) {
    const day = d.getDate()
    const month = d.toLocaleDateString('en-GB', { month: 'short' })
    return `around the week of ${day} ${month}`
  }
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '')
  const hasTime = /T\d{2}:/.test(iso) && !iso.endsWith('T23:59:59.000000Z')
  if (!hasTime) return day
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${day} · ${time}`
}
