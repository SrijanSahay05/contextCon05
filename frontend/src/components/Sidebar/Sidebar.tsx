import { animate } from 'animejs'
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { FOLDERS } from '../../data/folders'
import { hrefFor } from '../../hooks/useHashRoute'
import { prefersReducedMotion, springPop, springUI } from '../../lib/motion'
import type { Folder } from '../../types/startup'
import { Eye, Send, Sparkles, Tray } from '../Icons/Icons'
import './Sidebar.css'

const ICONS: Record<Folder, ReactNode> = {
  discover: <Sparkles />,
  watching: <Eye />,
  outreach: <Send size={18} />,
  discarded: <Tray />,
}

interface Props {
  /** The active folder, or null when another page (e.g. a startup) is open. */
  active: Folder | null
  counts: Record<Folder, number>
}

export function Sidebar({ active, counts }: Props) {
  const nav = useRef<HTMLElement>(null)
  const indicator = useRef<HTMLSpanElement>(null)
  const links = useRef<Partial<Record<Folder, HTMLAnchorElement | null>>>({})
  const badges = useRef<Partial<Record<Folder, HTMLSpanElement | null>>>({})
  const prevCounts = useRef(counts)
  const placed = useRef(false)

  // Slide the highlight to the active item. Springs retarget mid-flight,
  // so quick clicks stay continuous instead of jumping.
  useLayoutEffect(() => {
    const ind = indicator.current
    const link = active ? links.current[active] : null
    if (!ind) return
    if (!link) {
      ind.style.opacity = '0'
      return
    }
    const target = { y: link.offsetTop, height: link.offsetHeight, opacity: 1 }
    if (!placed.current || prefersReducedMotion()) {
      ind.style.transform = `translateY(${target.y}px)`
      ind.style.height = `${target.height}px`
      ind.style.opacity = '1'
      placed.current = true
      return
    }
    animate(ind, { ...target, ease: springUI() })
  }, [active])

  // When a folder gains an item, pop its count so the eye follows it.
  useEffect(() => {
    if (!prefersReducedMotion()) {
      for (const f of FOLDERS) {
        const badge = badges.current[f.id]
        if (badge && counts[f.id] > prevCounts.current[f.id]) {
          animate(badge, { scale: [1.35, 1], ease: springPop() })
        }
      }
    }
    prevCounts.current = counts
  }, [counts])

  return (
    <aside className="sidebar">
      <a className="sidebar__brand" href={hrefFor({ page: 'folder', folder: 'discover' })}>
        <span className="sidebar__mark" aria-hidden="true" />
        Scout
      </a>

      <nav ref={nav} className="sidebar__nav" aria-label="Folders">
        <span ref={indicator} className="sidebar__indicator" aria-hidden="true" />
        {FOLDERS.map((f) => (
          <a
            key={f.id}
            ref={(n) => void (links.current[f.id] = n)}
            href={hrefFor({ page: 'folder', folder: f.id })}
            className={`sidebar__item${active === f.id ? ' is-active' : ''}`}
            aria-current={active === f.id ? 'page' : undefined}
          >
            <span className="sidebar__icon">{ICONS[f.id]}</span>
            <span className="sidebar__label">{f.label}</span>
            <span className="sidebar__count" ref={(n) => void (badges.current[f.id] = n)}>
              {counts[f.id]}
            </span>
          </a>
        ))}
      </nav>

      <p className="sidebar__note">Sample data · prototype</p>
    </aside>
  )
}
