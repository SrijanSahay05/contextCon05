import { animate } from 'animejs'
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { EXIT_EASE, prefersReducedMotion, springUI } from '../../lib/motion'
import type { Folder, Item, StartupDetail } from '../../types/startup'
import { Close, Expand } from '../Icons/Icons'
import { Monogram } from '../Monogram/Monogram'
import { ScoreRing } from '../ScoreRing/ScoreRing'
import { StartupActions } from '../StartupActions/StartupActions'
import { StartupDetails } from '../StartupDetails/StartupDetails'
import './StartupModal.css'

interface Props {
  item: Item
  /** The card's rect, so the sheet grows out of it and returns to it. */
  origin: DOMRect | null
  onClose: () => void
  onOpenPage: () => void
  onMove: (to: Folder) => void
  onSchedule: () => void
  onDetailLoaded: (id: string, detail: StartupDetail) => void
}

/** Offset from the panel's centre to the origin card's centre, damped so it hints rather than flies. */
function offsetToOrigin(panel: HTMLElement, origin: DOMRect | null) {
  if (!origin) return { x: 0, y: 24 }
  const p = panel.getBoundingClientRect()
  return {
    x: (origin.left + origin.width / 2 - (p.left + p.width / 2)) * 0.3,
    y: (origin.top + origin.height / 2 - (p.top + p.height / 2)) * 0.3,
  }
}

export function StartupModal({ item, origin, onClose, onOpenPage, onMove, onSchedule, onDetailLoaded }: Props) {
  const scrim = useRef<HTMLDivElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const closing = useRef(false)

  // Enter: the sheet materialises from the direction of the card.
  useLayoutEffect(() => {
    const s = scrim.current
    const p = panel.current
    if (!s || !p) return
    if (prefersReducedMotion()) {
      animate([s, p], { opacity: [0, 1], duration: 160, ease: 'linear' })
      return
    }
    const from = offsetToOrigin(p, origin)
    animate(s, { opacity: [0, 1], duration: 240, ease: 'out(2)' })
    animate(p, { opacity: [0, 1], x: [from.x, 0], y: [from.y, 0], scale: [0.92, 1], ease: springUI() })
  }, [origin])

  // Exit along the same path in reverse, then unmount.
  const close = useCallback(
    (after?: () => void) => {
      const s = scrim.current
      const p = panel.current
      if (closing.current || !s || !p) return
      closing.current = true
      const finish = () => {
        onClose()
        after?.()
      }
      if (prefersReducedMotion()) {
        animate([s, p], { opacity: 0, duration: 140, ease: 'linear', onComplete: finish })
        return
      }
      const to = offsetToOrigin(p, origin)
      animate(s, { opacity: 0, duration: 200, ease: EXIT_EASE })
      animate(p, { opacity: 0, x: to.x, y: to.y, scale: 0.94, duration: 200, ease: EXIT_EASE, onComplete: finish })
    },
    [onClose, origin],
  )

  // Escape to close, lock page scroll, and manage focus.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    document.body.classList.add('is-locked')
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.classList.remove('is-locked')
      previous?.focus?.()
    }
  }, [close])

  return (
    <div className="modal" role="presentation">
      <div ref={scrim} className="modal__scrim" onClick={() => close()} />
      <div
        ref={panel}
        className="modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
      >
        <div className="modal__toolbar">
          <button type="button" className="btn btn--plain" onClick={() => close(onOpenPage)}>
            <Expand /> Open page
          </button>
          <button type="button" className="btn btn--icon" aria-label="Close" onClick={() => close()}>
            <Close />
          </button>
        </div>

        <div className="modal__scroll">
          <header className="modal__header">
            <Monogram name={item.name} hue={item.hue} size="lg" />
            <div className="modal__title">
              <h2 id="modal-title">{item.name}</h2>
              <p className="modal__tagline">{item.tagline}</p>
              <ul className="modal__meta">
                <li className="chip">{item.stage}</li>
                <li className="chip">{item.sector}</li>
                <li className="chip">{item.city}</li>
                {item.founded && <li className="chip">Founded {item.founded}</li>}
              </ul>
            </div>
            <ScoreRing score={item.score} size="lg" />
          </header>

          <StartupDetails item={item} onDetailLoaded={onDetailLoaded} />
        </div>

        <footer className="modal__footer">
          <span className="modal__founders">{item.teamLine}</span>
          <StartupActions item={item} onSchedule={onSchedule} onMove={(to) => close(() => onMove(to))} />
        </footer>
      </div>
    </div>
  )
}
