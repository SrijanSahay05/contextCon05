import { animate, stagger } from 'animejs'
import { useCallback, useEffect, useState, type RefObject } from 'react'
import { prefersReducedMotion } from '../lib/motion'

export type ScoutingPhase = 'list' | 'scouting'

/**
 * Hands the sheet between the card list and the scouting animation.
 * When a search starts, the cards clear out first, then the field appears.
 * When it ends, the field fades out and calls `onExited` to bring the list back.
 */
export function useScoutingPhase(busy: boolean, list: RefObject<HTMLElement | null>) {
  const [phase, setPhase] = useState<ScoutingPhase>('list')

  useEffect(() => {
    if (!busy || phase !== 'list') return
    const cards = list.current ? Array.from(list.current.children) : []
    if (!cards.length || prefersReducedMotion()) {
      const id = requestAnimationFrame(() => setPhase('scouting'))
      return () => cancelAnimationFrame(id)
    }
    const exit = animate(cards, {
      opacity: 0,
      y: -10,
      duration: 200,
      delay: stagger(25),
      ease: 'in(2)',
      onComplete: () => setPhase('scouting'),
    })
    // Stopped mid-exit: drop the half-run animation so the cards show again.
    return () => void exit.revert()
  }, [busy, phase, list])

  const onExited = useCallback(() => setPhase('list'), [])

  return { phase, onExited }
}
