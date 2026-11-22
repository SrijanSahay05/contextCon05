import { animate } from 'animejs'
import { useRef, useState } from 'react'
import { cadenceLabel } from '../../lib/format'
import { COLLAPSE_EASE, EXIT_EASE, prefersReducedMotion } from '../../lib/motion'
import type { Folder, Item } from '../../types/startup'
import { Clock } from '../Icons/Icons'
import { Monogram } from '../Monogram/Monogram'
import { ScoreRing } from '../ScoreRing/ScoreRing'
import { StartupActions } from '../StartupActions/StartupActions'
import './StartupCard.css'

interface Props {
  item: Item
  onMove: (id: string, to: Folder) => void
  onSchedule: (id: string) => void
  onOpen: (id: string, origin: DOMRect) => void
}

export function StartupCard({ item, onMove, onSchedule, onOpen }: Props) {
  const el = useRef<HTMLElement>(null)
  const [leaving, setLeaving] = useState(false)

  // Fade and slide the card out, collapse its height so the list closes
  // the gap smoothly, then hand the move to the store.
  const leave = (to: Folder) => {
    const node = el.current
    if (!node || leaving) return
    setLeaving(true)
    const done = () => onMove(item.id, to)
    if (prefersReducedMotion()) {
      animate(node, { opacity: 0, duration: 160, ease: 'linear', onComplete: done })
      return
    }
    animate(node, {
      opacity: 0,
      x: to === 'discarded' ? -24 : 24,
      scale: 0.97,
      duration: 200,
      ease: EXIT_EASE,
      onComplete: () => {
        node.style.overflow = 'hidden'
        animate(node, {
          height: [node.offsetHeight, 0],
          marginBottom: 0,
          paddingTop: 0,
          paddingBottom: 0,
          duration: 260,
          ease: COLLAPSE_EASE,
          onComplete: done,
        })
      },
    })
  }

  const open = () => {
    if (el.current && !leaving) onOpen(item.id, el.current.getBoundingClientRect())
  }

  return (
    <article
      ref={el}
      className="card"
      data-cursor="hover"
      onClick={(e) => {
        // Buttons inside the card do their own thing.
        if (!(e.target as Element).closest('button')) open()
      }}
    >
      <div className="card__main">
        <Monogram name={item.name} hue={item.hue} />
        <div className="card__body">
          <header className="card__head">
            <h3>
              <button type="button" className="card__title" onClick={open}>
                {item.name}
              </button>
            </h3>
            <span className="card__meta">
              {item.stage} · {item.city}
              {item.founded ? ` · Founded ${item.founded}` : ''}
              {item.source === 'sample' ? ' · Sample' : ''}
            </span>
          </header>
          <p className="card__tagline">{item.tagline}</p>
          <ul className="card__signals">
            {item.signals.map((s) => (
              <li key={s} className={s.startsWith('Can’t verify') ? 'chip chip--warn' : 'chip'}>
                {s}
              </li>
            ))}
          </ul>
          <p className="card__why">
            <strong>Why it fits</strong> {item.why}
          </p>
          <footer className="card__foot">
            <span className="card__founders">{item.teamLine}</span>
            {item.folder === 'watching' && (
              <span className={`card__status card__status--${item.momentum}`}>
                <Clock /> {cadenceLabel(item.cadenceDays)}
              </span>
            )}
            {item.folder === 'outreach' && item.outreach && (
              <span className="card__status card__status--high">
                <span className="card__dot" /> {item.outreach.status} · {item.outreach.nextStep}
              </span>
            )}
          </footer>
        </div>
        <ScoreRing score={item.score} />
      </div>

      <div className="card__actions">
        <StartupActions item={item} onMove={leave} onSchedule={() => onSchedule(item.id)} />
      </div>
    </article>
  )
}
