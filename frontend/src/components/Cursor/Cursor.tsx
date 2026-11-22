import { useEffect, useRef } from 'react'
import './Cursor.css'

const INTERACTIVE = 'button, a, [role="tab"], [data-cursor="hover"]'
const TEXT = 'textarea, input'

/**
 * A triangular pointer that tracks the mouse 1:1 (no lag: direct
 * manipulation). It tints and grows over interactive elements, turns
 * into an I-beam over text fields, and presses in on click.
 * Only active on fine pointers; touch keeps the native behaviour.
 */
export function Cursor() {
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = root.current
    if (!el || !window.matchMedia?.('(pointer: fine)').matches) return

    document.documentElement.classList.add('has-custom-cursor')

    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      el.dataset.visible = 'true'
      el.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`
    }
    const onOver = (e: PointerEvent) => {
      const t = e.target as Element | null
      el.dataset.mode = t?.closest(TEXT) ? 'text' : t?.closest(INTERACTIVE) ? 'hover' : 'idle'
    }
    const onDown = () => (el.dataset.down = 'true')
    const onUp = () => (el.dataset.down = 'false')
    const onLeave = () => (el.dataset.visible = 'false')

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerover', onOver)
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp)
    document.documentElement.addEventListener('pointerleave', onLeave)
    return () => {
      document.documentElement.classList.remove('has-custom-cursor')
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerover', onOver)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
      document.documentElement.removeEventListener('pointerleave', onLeave)
    }
  }, [])

  return (
    <div ref={root} className="cursor" data-visible="false" data-mode="idle" data-down="false" aria-hidden="true">
      <svg className="cursor__arrow" width="22" height="22" viewBox="0 0 22 22">
        {/* Tip sits at (2,2), which is the hotspot. */}
        <path d="M2 2 L19 9.2 L10.4 11.2 L8.6 19.6 Z" />
      </svg>
      <span className="cursor__beam" />
    </div>
  )
}
