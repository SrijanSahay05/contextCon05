import { animate, stagger } from 'animejs'
import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { ScoutingAnimation } from '../../components/ScoutingAnimation/ScoutingAnimation'
import { StartupCard } from '../../components/StartupCard/StartupCard'
import { folderMeta } from '../../data/folders'
import { useScoutingPhase } from '../../hooks/useScoutingPhase'
import { prefersReducedMotion, springUI } from '../../lib/motion'
import type { Folder, Item } from '../../types/startup'
import './FolderPage.css'

interface Props {
  folder: Folder
  items: Item[]
  /** Bumps when a new search lands, so the list re-animates. */
  runId: number
  busy: boolean
  /** Extra content under the title, e.g. the thesis composer on "For you". */
  intro?: ReactNode
  onMove: (id: string, to: Folder) => void
  onSchedule: (id: string) => void
  onOpen: (id: string, origin: DOMRect) => void
}

export function FolderPage({ folder, items, runId, busy, intro, onMove, onSchedule, onOpen }: Props) {
  const meta = folderMeta(folder)
  const list = useRef<HTMLDivElement>(null)
  const isDiscover = folder === 'discover'
  const { phase, onExited } = useScoutingPhase(busy, list)

  // Stagger cards in when the folder changes, or when the list returns after a search.
  useLayoutEffect(() => {
    if (phase !== 'list') return
    const cards = list.current?.children
    if (!cards?.length) return
    if (prefersReducedMotion()) {
      animate(cards, { opacity: [0, 1], duration: 180, ease: 'linear' })
      return
    }
    animate(cards, { opacity: [0, 1], y: [14, 0], delay: stagger(45), ease: springUI() })
  }, [folder, runId, phase])

  return (
    <div className={`folder-page${isDiscover ? ' folder-page--hero' : ''}`}>
      <header className="folder-page__header">
        <h1 className="display">{meta.title}</h1>
        <p className="folder-page__subtitle">{meta.subtitle}</p>
        {intro}
      </header>

      <section
        className={`folder-page__sheet${phase === 'scouting' ? ' is-scouting' : ''}`}
        aria-label={meta.label}
        aria-busy={busy}
      >
        {phase === 'scouting' ? (
          <ScoutingAnimation leaving={!busy} onExited={onExited} />
        ) : (
          <>
            <div ref={list} key={`${folder}-${runId}`}>
              {items.map((item) => (
                <StartupCard key={item.id} item={item} onMove={onMove} onSchedule={onSchedule} onOpen={onOpen} />
              ))}
            </div>
            {items.length === 0 && <p className="folder-page__empty">{meta.empty}</p>}
          </>
        )}
      </section>
    </div>
  )
}
