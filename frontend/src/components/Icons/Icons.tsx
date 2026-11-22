// Minimal line icons in the spirit of SF Symbols: 1.6px strokes, round caps.
import type { ReactNode } from 'react'

type IconProps = { size?: number }

function Icon({ size = 16, strokeWidth = 1.6, children }: IconProps & { strokeWidth?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const ArrowUp = ({ size = 18 }: IconProps) => (
  <Icon size={size} strokeWidth={2}>
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  </Icon>
)

export const ChevronLeft = ({ size = 16 }: IconProps) => (
  <Icon size={size} strokeWidth={2}>
    <path d="M15 5l-7 7 7 7" />
  </Icon>
)

export const Expand = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="M14 4h6v6M20 4l-8 8M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4" />
  </Icon>
)

export const Star = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" />
  </Icon>
)

export const Send = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="M20.5 3.5 10 14M20.5 3.5 14 20.5l-4-6.5-6.5-4z" />
  </Icon>
)

export const Close = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
)

export const Restore = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5" />
    <path d="M4 4v4.5h4.5" />
  </Icon>
)

export const Calendar = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <rect x="3.5" y="5" width="17" height="15" rx="3" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </Icon>
)

export const Link = ({ size = 18 }: IconProps) => (
  <Icon size={size}>
    <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
    <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
  </Icon>
)

export const Clock = ({ size = 13 }: IconProps) => (
  <Icon size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </Icon>
)

export const Sparkles = ({ size = 18 }: IconProps) => (
  <Icon size={size}>
    <path d="M12 3.5l1.7 4.8 4.8 1.7-4.8 1.7L12 16.5l-1.7-4.8L5.5 10l4.8-1.7z" />
    <path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" />
  </Icon>
)

export const Eye = ({ size = 18 }: IconProps) => (
  <Icon size={size}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
)

export const Tray = ({ size = 18 }: IconProps) => (
  <Icon size={size}>
    <path d="M3.5 13.5 6 5.5h12l2.5 8v4a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
    <path d="M3.5 13.5H8l1.5 2.5h5l1.5-2.5h4.5" />
  </Icon>
)

export const Newspaper = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
    <path d="M7.5 9h9M7.5 12.5h9M7.5 16h5" />
  </Icon>
)

export const Banknote = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
    <circle cx="12" cy="12" r="2.5" />
  </Icon>
)

export const People = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <circle cx="9" cy="8.5" r="3" />
    <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
    <path d="M15.5 5.8a3 3 0 0 1 0 5.4M17.5 14a5.5 5.5 0 0 1 3 5" />
  </Icon>
)

export const Gauge = ({ size = 16 }: IconProps) => (
  <Icon size={size}>
    <path d="M4 17a8 8 0 1 1 16 0" />
    <path d="M12 17l4-5" />
  </Icon>
)
