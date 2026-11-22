import { createAnimatable } from 'animejs'
import { useEffect, useRef } from 'react'
import { prefersReducedMotion } from '../../lib/motion'
import './Backdrop.css'

// One S-shaped "mountain road" (traced from the reference), extended past the
// top and bottom edges so it spans the whole screen. Wide, smooth turns.
const ROAD = 'M1000,-110 L630,45 C400,140 150,200 170,280 C190,360 520,450 560,555 C590,650 300,710 135,765 L-700,1040'

interface Layer {
  /** Zoom of this layer's roads; bigger reads as further away. */
  zoom: number
  spacing: number
  /** Share of the cursor drift this layer follows; lower feels deeper. */
  depth: number
}

// Back to front. The back layer is larger, fainter and moves less: parallax.
const LAYERS: Layer[] = [
  { zoom: 1.8, spacing: 64, depth: 0.4 },
  { zoom: 1, spacing: 46, depth: 1 },
]

const COUNT = 80
const INDEX_EVERY = 5 // every fifth line is bolder, like contour-map index lines

// How far (px) the front layer slides at the screen edges, and how long it takes to catch up (ms).
const DRIFT_X = 56
const DRIFT_Y = 40
const EASE_MS = 1100

/** Each line's offset, with spacing that gently widens and narrows like terrain. */
const offset = (i: number, spacing: number) => (i - 30) * spacing + Math.sin(i * 0.45) * spacing * 0.35

/** Decorative road lines behind the whole app, in two layers that drift with the cursor. */
export function Backdrop() {
  // Animate wrapper divs: on an <svg>, anime.js would set its x/y attributes instead.
  const layers = useRef<(HTMLDivElement | null)[]>([])

  useEffect(() => {
    if (prefersReducedMotion()) return
    const drifts = layers.current.map((el) => el && createAnimatable(el, { x: EASE_MS, y: EASE_MS, ease: 'out(3)' }))
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return // touch scrolling shouldn't slide the page
      // -1 … 1 from the centre of the window; the pattern slides the opposite way.
      const nx = (e.clientX / window.innerWidth) * 2 - 1
      const ny = (e.clientY / window.innerHeight) * 2 - 1
      drifts.forEach((drift, i) => {
        drift?.x(-nx * DRIFT_X * LAYERS[i].depth)
        drift?.y(-ny * DRIFT_Y * LAYERS[i].depth)
      })
    }
    window.addEventListener('pointermove', onMove)
    return () => {
      window.removeEventListener('pointermove', onMove)
      drifts.forEach((drift) => drift?.revert())
    }
  }, [])

  return (
    <div className="backdrop" aria-hidden="true">
      {LAYERS.map((layer, li) => (
        <div
          key={li}
          ref={(el) => void (layers.current[li] = el)}
          className={`backdrop__layer backdrop__layer--${li === 0 ? 'back' : 'front'}`}
        >
          <svg viewBox={`0 0 ${1000 / layer.zoom} ${1000 / layer.zoom}`} preserveAspectRatio="xMidYMid slice">
            {Array.from({ length: COUNT }, (_, i) => (
              <path
                key={i}
                d={ROAD}
                className={i % INDEX_EVERY === 0 ? 'is-index' : undefined}
                transform={`translate(${offset(i, layer.spacing)} 0)`}
              />
            ))}
          </svg>
        </div>
      ))}
    </div>
  )
}
