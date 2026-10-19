// Each scene's zone is the part of the picture zk marked to show (fractions of the
// image, set with the showroom's banner-zone tool). position is the fallback for
// scenes not yet marked.
export const SCENES = [
  { id: 'dinners', label: 'v1 dinners wallpaper', src: '/art/dinners.jpg', position: '50% 45%', zone: { x0: 0.000, y0: 0.318, x1: 1.000, y1: 0.931 } },
  { id: 'cookbook', label: 'v1 cookbook wallpaper', src: '/art/cookbook.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.276, x1: 1.000, y1: 0.889 } },
  { id: 'salon', label: 'v1 salon wallpaper', src: '/art/salon.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.271, x1: 1.000, y1: 0.884 } },
  { id: 'history', label: 'v1 history wallpaper', src: '/art/history.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.295, x1: 1.000, y1: 0.908 } },
  { id: 'bakehouse', label: 'autumn-bakehouse', src: '/art/bakehouse.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.240, x1: 1.000, y1: 0.853 } },
  { id: 'tureen', label: 'winter-kitchen', src: '/art/tureen.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.262, x1: 1.000, y1: 0.875 } },
  { id: 'larder-crates', label: 'winter-larder', src: '/art/larder-crates.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.215, x1: 1.000, y1: 0.828 } },
  { id: 'jars-lilac', label: 'spring-larder', src: '/art/jars-lilac.jpg', position: '50% 0%', zone: { x0: 0.000, y0: 0.177, x1: 1.000, y1: 0.790 } },
  { id: 'cider-press', label: 'autumn-kitchen', src: '/art/cider-press.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.387, x1: 1.000, y1: 1.000 } },
  { id: 'baking', label: 'winter-baking', src: '/art/baking.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.204, x1: 1.000, y1: 0.817 } },
  { id: 'orchard', label: 'autumn-orchard-table', src: '/art/orchard.jpg', position: '50% 100%', zone: { x0: 0.000, y0: 0.198, x1: 1.000, y1: 0.811 } },
  { id: 'connection', label: 'v1 connection wallpaper', src: '/art/connection.jpg', position: '50% 50%' },
  { id: 'notebook', label: 'v1 notebook wallpaper', src: '/art/notebook.jpg', position: '50% 50%' },
  { id: 'autumn-glasshouse', label: 'autumn-glasshouse', src: '/art/autumn-glasshouse.jpg', position: '50% 50%' },
  { id: 'autumn-potager', label: 'autumn-potager', src: '/art/autumn-potager.jpg', position: '50% 50%' },
  { id: 'autumn-table-wallpaper', label: 'autumn-table-wallpaper', src: '/art/autumn-table-wallpaper.jpg', position: '50% 50%' },
  { id: 'spring-breakfast', label: 'spring-breakfast', src: '/art/spring-breakfast.jpg', position: '50% 50%' },
  { id: 'spring-garden', label: 'spring-garden', src: '/art/spring-garden.jpg', position: '50% 50%' },
  { id: 'spring-table', label: 'spring-table', src: '/art/spring-table.jpg', position: '50% 50%' },
  { id: 'spring-tea-wallpaper', label: 'spring-tea-wallpaper', src: '/art/spring-tea-wallpaper.jpg', position: '50% 50%' },
  { id: 'spring-veranda', label: 'spring-veranda', src: '/art/spring-veranda.jpg', position: '50% 50%' },
  { id: 'summer-garden', label: 'summer-garden', src: '/art/summer-garden.jpg', position: '50% 50%' },
  { id: 'summer-jam-wallpaper', label: 'summer-jam-wallpaper', src: '/art/summer-jam-wallpaper.jpg', position: '50% 50%' },
  { id: 'summer-kitchen-pots', label: 'summer-kitchen-pots', src: '/art/summer-kitchen-pots.jpg', position: '50% 50%' },
  { id: 'summer-pergola', label: 'summer-pergola', src: '/art/summer-pergola.jpg', position: '50% 50%' },
  { id: 'summer-picnic', label: 'summer-picnic', src: '/art/summer-picnic.jpg', position: '50% 50%' },
  { id: 'summer-terrace-pots', label: 'summer-terrace-pots', src: '/art/summer-terrace-pots.jpg', position: '50% 50%' },
  { id: 'winter-glasshouse', label: 'winter-glasshouse', src: '/art/winter-glasshouse.jpg', position: '50% 50%' },
  { id: 'winter-picnic', label: 'winter-picnic', src: '/art/winter-picnic.jpg', position: '50% 50%' },
  { id: 'winter-table-wallpaper', label: 'winter-table-wallpaper', src: '/art/winter-table-wallpaper.jpg', position: '50% 50%' },
]

export function sceneById(id) {
  return SCENES.find((scene) => scene.id === id) || SCENES[0]
}

// Banner art is 1280 x 720. The crop covers the banner, centres on the zone, and
// zooms in (at most MAX_ZOOM) until the zone fills it, never leaving bare edges.
export const ART_W = 1280
export const ART_H = 720
export const MAX_ZOOM = 1.6

export function cropFor(bw, bh, zone, w = ART_W, h = ART_H) {
  const cover = Math.max(bw / w, bh / h)
  const fit = Math.min(bw / ((zone.x1 - zone.x0) * w), bh / ((zone.y1 - zone.y0) * h))
  const scale = Math.max(cover, Math.min(fit, cover * MAX_ZOOM))
  const dw = w * scale
  const dh = h * scale
  const cx = ((zone.x0 + zone.x1) / 2) * dw
  const cy = ((zone.y0 + zone.y1) / 2) * dh
  return {
    width: dw,
    height: dh,
    left: -Math.min(Math.max(cx - bw / 2, 0), dw - bw),
    top: -Math.min(Math.max(cy - bh / 2, 0), dh - bh),
  }
}
