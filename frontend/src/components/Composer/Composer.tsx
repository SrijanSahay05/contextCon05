import { useLayoutEffect, useRef, useState } from 'react'
import type { SearchPlan, SearchStatus } from '../../types/startup'
import { ArrowUp, Link } from '../Icons/Icons'
import './Composer.css'

interface Props {
  /** The latest search, shown under the field. */
  status: SearchStatus | null
  onSubmit: (text: string) => void
}

const PLACEHOLDER =
  'Describe your thesis: sectors, stage, cheque size, what you always pass on… or paste your LinkedIn profile and we’ll build it for you.'

const MAX_HEIGHT = 200
const LINKEDIN = /linkedin\.com\/in\//i
const CHIP_MAX = 90

const clip = (text: string) => (text.length > CHIP_MAX ? `${text.slice(0, CHIP_MAX)}…` : text)

/** A one-line, human summary of the filters the search actually used. */
function describePlan(plan: SearchPlan) {
  const parts = [plan.country, plan.foundedAfter && `founded ${plan.foundedAfter}+`]
  if (plan.minHeadcount || plan.maxHeadcount) parts.push(`${plan.minHeadcount ?? 1}–${plan.maxHeadcount ?? '∞'} people`)
  parts.push(plan.planner === 'claude' ? 'planned by Claude' : 'rule-based plan')
  return parts.filter(Boolean).join(' · ')
}

export function Composer({ status, onSubmit }: Props) {
  const busy = status?.state === 'busy'
  const [value, setValue] = useState('')
  const field = useRef<HTMLTextAreaElement>(null)

  // Grow with the text, up to a cap.
  useLayoutEffect(() => {
    const t = field.current
    if (!t) return
    t.style.height = '0px'
    t.style.height = `${Math.min(t.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    onSubmit(text)
    setValue('')
  }

  const isLinkedIn = LINKEDIN.test(value)

  return (
    <>
      <form
        className={`composer${busy ? ' is-busy' : ''}`}
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <textarea
          ref={field}
          className="composer__field"
          rows={1}
          value={value}
          placeholder={PLACEHOLDER}
          aria-label="Your investment thesis"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <div className="composer__bar">
          <span className={`composer__hint${isLinkedIn ? ' is-on' : ''}`}>
            <Link size={15} />
            {isLinkedIn
              ? 'LinkedIn import isn’t live yet. Describe your thesis in words for now.'
              : 'Sectors, stage, geography, what you avoid'}
          </span>
          <button type="submit" className="composer__send" aria-label="Find startups" disabled={!value.trim() || busy}>
            <ArrowUp />
          </button>
        </div>
      </form>
      {status?.state === 'busy' && (
        <p className="composer__status">
          Scouting for <strong>“{clip(status.thesis)}”</strong>
        </p>
      )}
      {status?.state === 'done' && (
        <div className="composer__status">
          <p>
            {status.count} {status.count === 1 ? 'startup' : 'startups'} for <strong>“{clip(status.thesis)}”</strong>
            {' · '}
            {status.credits > 0 ? `${status.credits.toFixed(2)} credits` : 'cached, no credits'}
          </p>
          <p className="composer__plan">
            Searched for “{clip(status.plan.query)}” · {describePlan(status.plan)}
          </p>
        </div>
      )}
      {status?.state === 'error' && (
        <p className="composer__status composer__status--error" role="alert">
          {status.message}
        </p>
      )}
    </>
  )
}
