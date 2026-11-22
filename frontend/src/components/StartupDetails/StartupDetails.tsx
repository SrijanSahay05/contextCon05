import { animate, stagger } from 'animejs'
import { useEffect, useRef, type ReactNode } from 'react'
import { formatDate, growthPct } from '../../lib/format'
import { prefersReducedMotion } from '../../lib/motion'
import type { Item, ScoreBreakdown, StartupDetail } from '../../types/startup'
import { Banknote, Gauge, Newspaper, People } from '../Icons/Icons'
import './StartupDetails.css'

const BREAKDOWN_LABELS: Record<keyof ScoreBreakdown, string> = {
  thesis: 'Thesis fit',
  momentum: 'Momentum',
  hiring: 'Hiring',
  timing: 'Timing',
}

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="details__section">
      <h4 className="details__heading">
        {icon}
        {title}
      </h4>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="details__empty">{children}</p>
}

function ScoreSection({ item }: { item: Item }) {
  const bars = useRef<HTMLDivElement>(null)

  // Grow the score bars from the left (transform only, so it stays at 60fps).
  useEffect(() => {
    const fills = bars.current?.querySelectorAll('.details__bar-fill')
    if (!fills?.length || prefersReducedMotion()) return
    const a = animate(fills, { scaleX: [0, 1], duration: 700, delay: stagger(60, { start: 120 }), ease: 'out(4)' })
    return () => void a.revert()
  }, [item.id])

  return (
    <Section icon={<Gauge />} title="Why it scores">
      <p className="details__why">{item.why}</p>
      <div ref={bars} className="details__bars">
        {(Object.keys(BREAKDOWN_LABELS) as (keyof ScoreBreakdown)[]).map((k) => {
          const value = item.breakdown[k]
          return (
            <div key={k} className="details__bar">
              <span>{BREAKDOWN_LABELS[k]}</span>
              {value == null ? (
                <span className="details__bar-missing">Can’t verify</span>
              ) : (
                <span className="details__bar-track">
                  <span className="details__bar-fill" style={{ width: `${value}%` }} />
                </span>
              )}
              <span className="details__bar-value">{value ?? '—'}</span>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

function HiringSection({ detail }: { detail: StartupDetail }) {
  const { now, sixMonthsAgo } = detail.headcount
  const growth = now != null && sixMonthsAgo ? growthPct(now, sixMonthsAgo) : null
  return (
    <Section icon={<People />} title="Hiring">
      <div className="details__stats">
        <div>
          <span className="details__stat">{now ?? '—'}</span>
          <span className="details__stat-label">people today</span>
        </div>
        <div>
          <span className={`details__stat${growth != null && growth > 0 ? ' is-up' : ''}`}>
            {growth == null ? '—' : `${growth > 0 ? '+' : ''}${growth}%`}
          </span>
          <span className="details__stat-label">in 6 months</span>
        </div>
        <div>
          <span className="details__stat">{detail.openRoles.length || '—'}</span>
          <span className="details__stat-label">open roles</span>
        </div>
      </div>
      <h5 className="details__subheading">Recent leadership hires</h5>
      {detail.hires.length > 0 ? (
        <ul className="details__list">
          {detail.hires.map((h) => (
            <li key={`${h.person}-${h.date}`} className="details__row">
              <div>
                <span className="details__primary">
                  {h.person}, {h.role}
                </span>
                <span className="details__secondary">Previously at {h.from}</span>
              </div>
              <time className="details__date">{formatDate(h.date)}</time>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No dated leadership hires in the last 18 months.</Empty>
      )}
      {detail.openRoles.length > 0 && (
        <ul className="details__chips">
          {detail.openRoles.map((r) => (
            <li key={r} className="chip">
              {r}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function NewsSection({ detail }: { detail: StartupDetail }) {
  return (
    <Section icon={<Newspaper />} title="News">
      {!detail.newsVerified && detail.news.length > 0 && (
        <p className="details__caveat">Matched by name only. Some stories may be about a namesake.</p>
      )}
      {detail.news.length > 0 ? (
        <ul className="details__list">
          {detail.news.map((n) => (
            <li key={`${n.date}-${n.title}`} className="details__row">
              <div>
                {n.url ? (
                  <a className="details__primary details__link" href={n.url} target="_blank" rel="noreferrer">
                    {n.title}
                  </a>
                ) : (
                  <span className="details__primary">{n.title}</span>
                )}
                <span className="details__secondary">{n.source}</span>
              </div>
              {n.date && <time className="details__date">{formatDate(n.date)}</time>}
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No coverage found that is clearly about this company.</Empty>
      )}
    </Section>
  )
}

function FundingSection({ detail }: { detail: StartupDetail }) {
  const grants = detail.funding.filter((f) => f.kind === 'grant')
  const rounds = detail.funding.filter((f) => f.kind === 'round')
  return (
    <Section icon={<Banknote />} title="Grants & funding">
      {detail.funding.length > 0 && (
        <ul className="details__list">
          {[...grants, ...rounds].map((f) => (
            <li key={`${f.date}-${f.name}`} className="details__row">
              <div>
                <span className="details__primary">
                  <span className={`chip ${f.kind === 'grant' ? 'chip--accent' : ''}`}>
                    {f.kind === 'grant' ? 'Grant' : 'Round'}
                  </span>
                  {f.name} · {f.amount}
                </span>
                <span className="details__secondary">{f.detail}</span>
              </div>
              <time className="details__date">{formatDate(f.date)}</time>
            </li>
          ))}
        </ul>
      )}
      {grants.length === 0 && <Empty>No grants found in the records.</Empty>}
      {rounds.length === 0 && <Empty>No disclosed funding rounds.</Empty>}
    </Section>
  )
}

interface Props {
  item: Item
  layout?: 'compact' | 'full'
}

/** The body shared by the quick-look modal and the full startup page. */
export function StartupDetails({ item, layout = 'compact' }: Props) {
  return (
    <div className={`details details--${layout}`}>
      <ScoreSection item={item} />
      <HiringSection detail={item.detail} />
      <NewsSection detail={item.detail} />
      <FundingSection detail={item.detail} />
    </div>
  )
}
