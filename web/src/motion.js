export const MOTIONS = {
  drawer: { duration: 0.28, ease: [0.55, 0, 0.45, 1] },
  flip: { duration: 0.45, ease: [0.22, 0.8, 0.3, 1] },
  banner: { duration: 1.2, ease: [0.65, 0, 0.35, 1] },
}

export function transition(reduced, name) {
  if (reduced) return { duration: 0 }
  return MOTIONS[name]
}
