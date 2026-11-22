import { animate } from 'animejs'
import { useEffect, useRef } from 'react'
import { prefersReducedMotion } from '../../lib/motion'
import './ScoreRing.css'

const R = 22
const C = 2 * Math.PI * R

function tone(score: number) {
  if (score >= 85) return 'strong'
  if (score >= 70) return 'good'
  return 'weak'
}

interface Props {
  score: number
  size?: 'md' | 'lg'
}

/** Fit score as a ring that fills and counts up on mount. */
export function ScoreRing({ score, size = 'md' }: Props) {
  const arc = useRef<SVGCircleElement>(null)
  const num = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const target = C * (1 - score / 100)
    if (!arc.current || !num.current) return
    if (prefersReducedMotion()) {
      arc.current.style.strokeDashoffset = String(target)
      num.current.textContent = String(score)
      return
    }
    const counter = { v: 0 }
    const ring = animate(arc.current, { strokeDashoffset: [C, target], duration: 900, ease: 'out(4)' })
    const count = animate(counter, {
      v: score,
      duration: 900,
      ease: 'out(4)',
      modifier: Math.round,
      onUpdate: () => {
        if (num.current) num.current.textContent = String(counter.v)
      },
    })
    return () => {
      ring.revert()
      count.revert()
    }
  }, [score])

  return (
    <div
      className={`score score--${tone(score)} score--${size}`}
      role="img"
      aria-label={`Fit score ${score} out of 100`}
    >
      <svg viewBox="0 0 56 56" aria-hidden="true">
        <circle className="score__track" cx="28" cy="28" r={R} />
        <circle
          ref={arc}
          className="score__arc"
          cx="28"
          cy="28"
          r={R}
          strokeDasharray={C}
          strokeDashoffset={C}
          transform="rotate(-90 28 28)"
        />
      </svg>
      <span ref={num} className="score__num">
        0
      </span>
    </div>
  )
}
