export const duration = {
  fast: 0.15,
  base: 0.25,
  slow: 0.4,
} as const

export const durationMs = {
  fast: 150,
  base: 250,
  slow: 400,
} as const

export const ease = [0.4, 0, 0.2, 1] as const

export const spring = {
  type: 'spring',
  stiffness: 300,
  damping: 30,
} as const
