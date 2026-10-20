import { LEVELS, MASK_PX, SEPIA, WET } from './constants.js'

let ready = false
const urls = []

function buildField(n) {
  const rnd = Array.from({ length: 64 }, () => Math.random())
  const at = (x, y, p) => rnd[(((y % p) + p) % p) * 8 + (((x % p) + p) % p)]
  const smooth = (t) => t * t * (3 - 2 * t)
  const field = new Float32Array(n * n)
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      let v = 0
      let amp = 0.7
      let f = 3 / n
      for (let o = 0; o < 2; o++) {
        const fx = x * f
        const fy = y * f
        const ix = Math.floor(fx)
        const iy = Math.floor(fy)
        const u = smooth(fx - ix)
        const w = smooth(fy - iy)
        const p = 3 << o
        const a = at(ix, iy, p)
        const b = at(ix + 1, iy, p)
        const c = at(ix, iy + 1, p)
        const d = at(ix + 1, iy + 1, p)
        v += amp * ((a * (1 - u) + b * u) * (1 - w) + (c * (1 - u) + d * u) * w)
        amp *= 0.4
        f *= 2
      }
      field[y * n + x] = v / 0.98
    }
  }
  return field
}

function levelBlob(field, n, cover) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = n
  const ctx = canvas.getContext('2d')
  const img = ctx.createImageData(n, n)
  for (let i = 0; i < n * n; i++) {
    const edge = Math.min(1, Math.max(0, (cover - field[i]) / 0.2 + 0.5))
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = 255
    img.data[i * 4 + 3] = Math.round(edge * 255)
  }
  ctx.putImageData(img, 0, 0)
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob ? URL.createObjectURL(blob) : null), 'image/png')
  })
}

// Build noise-mask levels once and inject the seep keyframes. Safe to call often.
export async function ensureSeepStyles() {
  if (ready || typeof document === 'undefined') return
  ready = true
  const n = MASK_PX
  const field = buildField(n)
  const covers = Array.from({ length: LEVELS }, (_, k) => 0.04 + (k / (LEVELS - 1)) * 0.98)
  const built = await Promise.all(covers.map((cover) => levelBlob(field, n, cover)))
  // Decode each mask before anything animates with it. The first animation
  // after a load otherwise paints while its mask images are still undecoded,
  // and that first trace step flickers before the rest seep in cleanly.
  await Promise.all(
    built.map((url) => {
      if (!url) return null
      const img = new Image()
      img.src = url
      return img.decode().catch(() => {})
    }),
  )
  built.forEach((url, k) => {
    if (url) {
      urls.push(url)
      document.documentElement.style.setProperty('--seep-' + k, `url("${url}")`)
    }
  })
  const frames = covers.map((_, k) => `${((k / LEVELS) * 92).toFixed(2)}% { -webkit-mask-image: var(--seep-${k}); mask-image: var(--seep-${k}); }`)
  const style = document.createElement('style')
  style.setAttribute('data-ink-seep', '')
  style.textContent = `
@keyframes ink-seep { ${frames.join(' ')} 92%, 100% { -webkit-mask-image: none; mask-image: none; } }
@keyframes ink-seep-dry {
  0% { color: ${WET}; }
  100% { color: ${SEPIA}; }
}
.ink-host .ink-c {
  opacity: 0;
}
.ink-host .ink-c.on {
  opacity: 1;
  -webkit-mask-repeat: repeat;
  mask-repeat: repeat;
  -webkit-mask-size: 2.4em 2.4em;
  mask-size: 2.4em 2.4em;
  -webkit-mask-position: var(--mx) var(--my);
  mask-position: var(--mx) var(--my);
  animation: ink-seep var(--d, 360ms) linear forwards, ink-seep-dry calc(var(--d, 360ms) * 1.8) ease-out forwards;
}
.ink-host { contain: layout paint; }
.ink-host.ink-plain .ink-c,
.ink-host.ink-plain .ink-c.on {
  opacity: 1;
  animation: none;
  color: inherit;
  -webkit-mask-image: none;
  mask-image: none;
}
@media (prefers-reduced-motion: reduce) {
  .ink-host .ink-c, .ink-host .ink-c.on {
    opacity: 1 !important;
    animation: none !important;
    color: inherit !important;
    -webkit-mask-image: none !important;
    mask-image: none !important;
  }
}
`
  document.head.append(style)
}

export function seepUrlsForTests() {
  return urls
}
