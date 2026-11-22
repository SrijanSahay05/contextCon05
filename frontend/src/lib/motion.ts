import { spring } from 'animejs'

// Apple-style defaults: critically damped (no bounce) for UI movement,
// a little bounce only where something "lands" (badges, counts).
export const springUI = () => spring({ bounce: 0, duration: 380 })
export const springPop = () => spring({ bounce: 0.35, duration: 420 })

// Exits are not interactive, so short eased tweens keep them snappy.
export const EXIT_EASE = 'out(3)'
export const COLLAPSE_EASE = 'inOut(3)'

export const prefersReducedMotion = () =>
  typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
