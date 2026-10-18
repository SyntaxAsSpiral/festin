// Crop positions are the mock's per-scene object-position (mock2 slip column).
// art-inventory.md had not landed when these were written.
export const SCENES = [
  { id: 'dinners', label: 'v1 dinners wallpaper', src: '/art/dinners.jpg', position: '50% 45%' },
  { id: 'cookbook', label: 'v1 cookbook wallpaper', src: '/art/cookbook.jpg', position: '50% 100%' },
  { id: 'salon', label: 'v1 salon wallpaper', src: '/art/salon.jpg', position: '50% 100%' },
  { id: 'history', label: 'v1 history wallpaper', src: '/art/history.jpg', position: '50% 100%' },
  { id: 'bakehouse', label: 'autumn-bakehouse', src: '/art/bakehouse.jpg', position: '50% 100%' },
  { id: 'tureen', label: 'winter-kitchen', src: '/art/tureen.jpg', position: '50% 100%' },
  { id: 'larder-crates', label: 'winter-larder', src: '/art/larder-crates.jpg', position: '50% 100%' },
  { id: 'jars-lilac', label: 'spring-larder', src: '/art/jars-lilac.jpg', position: '50% 0%' },
  { id: 'cider-press', label: 'autumn-kitchen', src: '/art/cider-press.jpg', position: '50% 100%' },
  { id: 'baking', label: 'winter-baking', src: '/art/baking.jpg', position: '50% 100%' },
  { id: 'orchard', label: 'autumn-orchard-table', src: '/art/orchard.jpg', position: '50% 100%' },
]

export function sceneById(id) {
  return SCENES.find((scene) => scene.id === id) || SCENES[0]
}
