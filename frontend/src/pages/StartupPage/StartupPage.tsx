import { animate, stagger } from 'animejs'
import { useLayoutEffect, useRef } from 'react'
import { ChevronLeft } from '../../components/Icons/Icons'
import { Monogram } from '../../components/Monogram/Monogram'
import { ScoreRing } from '../../components/ScoreRing/ScoreRing'
import { StartupActions } from '../../components/StartupActions/StartupActions'
import { StartupDetails } from '../../components/StartupDetails/StartupDetails'
import { folderMeta } from '../../data/folders'
import { hrefFor } from '../../hooks/useHashRoute'
import { prefersReducedMotion, springUI } from '../../lib/motion'
import type { Folder, Item } from '../../types/startup'
import './StartupPage.css'

interface Props {
  item: Item | undefined
  onMove: (id: string, to: Folder) => void
  onSchedule: (id: string) => void
}

/** The full page for one startup. Actions keep you here; the status chip updates. */
export function StartupPage({ item, onMove, onSchedule }: Props) {
  const root = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!root.current || prefersReducedMotion()) return
    animate(root.current.children, { opacity: [0, 1], y: [12, 0], delay: stagger(60), ease: springUI() })
  }, [item?.id])

  if (!item) {
    return (
      <div className="startup-page startup-page--missing">
        <p>We couldn’t find that startup.</p>
        <a className="btn btn--tinted" href={hrefFor({ page: 'folder', folder: 'discover' })}>
          Back to For you
        </a>
      </div>
    )
  }

  const folder = folderMeta(item.folder)

  return (
    <div ref={root} className="startup-page">
      <a className="startup-page__back" href={hrefFor({ page: 'folder', folder: item.folder })}>
        <ChevronLeft /> {folder.label}
      </a>

      <header className="startup-page__header">
        <Monogram name={item.name} hue={item.hue} size="lg" />
        <div className="startup-page__title">
          <h1 className="display">{item.name}</h1>
          <p className="startup-page__tagline">{item.tagline}</p>
          <ul className="startup-page__meta">
            <li className="chip chip--accent">{folder.status}</li>
            <li className="chip">{item.stage}</li>
            <li className="chip">{item.sector}</li>
            <li className="chip">{item.city}</li>
            {item.founded && <li className="chip">Founded {item.founded}</li>}
          </ul>
          <p className="startup-page__founders">{item.teamLine}</p>
        </div>
        <ScoreRing score={item.score} size="lg" />
      </header>

      <div className="startup-page__actions">
        <StartupActions
          item={item}
          size="lg"
          onMove={(to) => onMove(item.id, to)}
          onSchedule={() => onSchedule(item.id)}
        />
      </div>

      <StartupDetails item={item} layout="full" />
    </div>
  )
}
