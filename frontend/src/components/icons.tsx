import type { ReactNode } from 'react'

/**
 * The app's few icons, as inline SVG: no icon library. Every icon is decorative
 * (`aria-hidden`); the control or message around it carries the meaning in words.
 *
 * Keep `17` out of the path data: the numbers page's "never reveals" test scans the whole
 * `innerHTML`, attributes included, for its stubbed drawn number 17 (and its Korean
 * text), and an icon can be on screen before the answer is.
 */
function Svg({ className, children }: { className: string; children: ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {children}
    </svg>
  )
}

/** A speaker with sound waves: plays the question's audio again. */
export function ReplayIcon({ className = 'size-8' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M4 9.5h3l5-4v13l-5-4H4z" />
      <path d="M16 9a4.5 4.5 0 0 1 0 6" />
      <path d="M19 6a8.5 8.5 0 0 1 0 12" />
    </Svg>
  )
}

export function CheckIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M5.5 12.5l4.5 4.5 8.5-9.5" />
    </Svg>
  )
}

export function CrossIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M7.5 7.5l9 9M7.5 16.5l9-9" />
    </Svg>
  )
}

export function AlertIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 6.5v7" />
      <path d="M12 18h.01" />
    </Svg>
  )
}

export function EyeIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.5" />
    </Svg>
  )
}

/** A phone keypad: the numbers exercise, in the navigation. */
export function KeypadIcon({ className = 'size-6' }: { className?: string }) {
  return (
    <Svg className={className}>
      {[4, 9.5, 15].map((y) =>
        [6, 12, 18].map((x) => <circle key={`${x},${y}`} cx={x} cy={y} r={1} />),
      )}
      <circle cx={12} cy={20.5} r={1} />
    </Svg>
  )
}

/** An open book: the vocabulary, in the navigation. */
export function BookIcon({ className = 'size-6' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5c-3.5-.5-6.5 0-8.5 1.5z" />
      <path d="M12 6.5v13" />
    </Svg>
  )
}

export function ChevronDownIcon({ className = 'size-5' }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M6.5 9.5 12 15l5.5-5.5" />
    </Svg>
  )
}
