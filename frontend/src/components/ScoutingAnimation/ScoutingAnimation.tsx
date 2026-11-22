import { animate } from 'animejs'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { prefersReducedMotion, springUI } from '../../lib/motion'
import { createScoutField } from './scoutField'
import './ScoutingAnimation.css'

const STEPS = ['Reading your thesis', 'Scanning companies', 'Checking momentum', 'Ranking the best fits']
const STEP_MS = 800
const MAX_DT = 1 / 30

interface Props {
  /** True once the search is done; the field fades out, then calls onExited. */
  leaving: boolean
  onExited: () => void
}

/** Shown in place of the list while a search runs: startups streaming past a fund that pulls some in. */
export function ScoutingAnimation({ leaving, onExited }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [step, setStep] = useState(0)

  // Particle field: sized to the container, drawn every frame.
  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const field = createScoutField(ctx)
    const still = prefersReducedMotion()

    const fit = () => {
      const { width, height } = el.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      el.width = Math.round(width * dpr)
      el.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      field.resize(width, height)
      if (still) field.draw()
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)

    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      field.step(Math.min((now - last) / 1000, MAX_DT))
      field.draw()
      last = now
      frame = requestAnimationFrame(tick)
    }
    if (!still) frame = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  // Cycle the status line.
  useEffect(() => {
    const id = window.setInterval(() => setStep((s) => (s + 1) % STEPS.length), STEP_MS)
    return () => window.clearInterval(id)
  }, [])

  // Enter: materialise. Exit: fade and lift away, then hand back to the list.
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    if (prefersReducedMotion()) {
      animate(el, leaving ? { opacity: 0, duration: 120, onComplete: onExited } : { opacity: [0, 1], duration: 160 })
      return
    }
    if (leaving) {
      animate(el, { opacity: 0, scale: 1.02, duration: 220, ease: 'out(3)', onComplete: onExited })
    } else {
      animate(el, { opacity: [0, 1], scale: [0.98, 1], ease: springUI() })
    }
  }, [leaving, onExited])

  return (
    <div ref={root} className="scouting" role="status" aria-live="polite">
      <canvas ref={canvas} className="scouting__canvas" aria-hidden="true" />
      <p className="scouting__label">
        <span key={step} className="scouting__step">
          {STEPS[step]}
        </span>
        <span className="scouting__dots" aria-hidden="true" />
      </p>
    </div>
  )
}
