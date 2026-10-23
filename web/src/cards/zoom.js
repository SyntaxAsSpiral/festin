// Geometry for the scan viewer. A view is { s, x, y, r }: scale against the image's own
// pixels, the image centre's offset from the stage centre (px), and a turn in degrees
// (a multiple of 90). Points are given the same way, as offsets from the stage centre.

const sideways = (r) => (((r / 90) % 2) + 2) % 2 === 1

// The image's size on screen at scale 1, turned.
function turned(img, r) {
  return sideways(r) ? { w: img.h, h: img.w } : img
}

export function fitScale(img, box, r = 0) {
  const t = turned(img, r)
  if (!t.w || !t.h || !box.w || !box.h) return 1
  return Math.min(box.w / t.w, box.h / t.h)
}

export function limits(img, box, r = 0) {
  const min = fitScale(img, box, r)
  return { min, max: Math.max(4, min * 4) }
}

export function fitView(img, box, r = 0) {
  return { s: fitScale(img, box, r), x: 0, y: 0, r }
}

export function isFitted(v, img, box) {
  return v.s <= fitScale(img, box, v.r) * 1.001
}

// Keep the scale within its limits and the image over the stage: an axis smaller than
// the stage is centred on it, a larger one may not pull its edge inside.
export function clampView(v, img, box) {
  const { min, max } = limits(img, box, v.r)
  const s = Math.min(max, Math.max(min, v.s))
  const t = turned(img, v.r)
  const room = (side, stage) => Math.max(0, (side * s - stage) / 2)
  const rx = room(t.w, box.w)
  const ry = room(t.h, box.h)
  return { ...v, s, x: Math.min(rx, Math.max(-rx, v.x)), y: Math.min(ry, Math.max(-ry, v.y)) }
}

// Zoom by k about point (px, py): that point of the image stays under it.
export function zoomAt(v, k, px, py, img, box) {
  const { min, max } = limits(img, box, v.r)
  const s = Math.min(max, Math.max(min, v.s * k))
  const kk = s / v.s
  return clampView({ ...v, s, x: px + (v.x - px) * kk, y: py + (v.y - py) * kk }, img, box)
}

export function panBy(v, dx, dy, img, box) {
  return clampView({ ...v, x: v.x + dx, y: v.y + dy }, img, box)
}

// A quarter turn clockwise about the stage centre, so what sits there stays there. A
// fitted image stays fitted to its new shape.
export function rotateView(v, img, box) {
  const r = v.r + 90 // never wrapped, so an eased turn always goes clockwise
  if (isFitted(v, img, box)) return fitView(img, box, r)
  return clampView({ ...v, r, x: -v.y, y: v.x }, img, box)
}
