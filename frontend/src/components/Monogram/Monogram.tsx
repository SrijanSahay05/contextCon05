import type { CSSProperties } from 'react'
import './Monogram.css'

interface Props {
  name: string
  hue: number
  size?: 'md' | 'lg'
}

export function Monogram({ name, hue, size = 'md' }: Props) {
  return (
    <div className={`monogram monogram--${size}`} style={{ '--hue': hue } as CSSProperties} aria-hidden="true">
      {name[0]}
    </div>
  )
}
