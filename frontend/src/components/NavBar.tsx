import type { ReactNode } from 'react'

export interface NavItem {
  href: string
  label: string
  /** Decorative: the label names the link. */
  icon: ReactNode
  current: boolean
}

// The current page is marked by `aria-current="page"`, and styled from that attribute, so
// what a screen reader hears and what the eye sees cannot disagree. A filled pill as well as
// a colour: colour is never the only signal.
const LINK =
  'flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-field px-3 py-1.5 ' +
  'text-sm font-bold text-muted transition-colors duration-150 hover:text-primary ' +
  'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
  'aria-[current=page]:bg-primary-soft aria-[current=page]:text-primary ' +
  'sm:min-h-12 sm:flex-row sm:gap-2 sm:rounded-full sm:px-5 sm:text-base'

/**
 * The app's navigation: a `<nav>` landmark with one native link per page, icon over label
 * on a phone, side by side from `sm:` up. `className` places the bar (a bottom tab bar on a
 * phone, a top bar wider up); its look is the primitive's.
 */
export function NavBar({ items, className }: { items: NavItem[]; className?: string }) {
  return (
    <nav aria-label="Main" className={`bg-surface/95 backdrop-blur ${className ?? ''}`.trim()}>
      <ul className="mx-auto flex max-w-xl justify-center gap-1 px-2 py-1.5 sm:gap-2">
        {items.map((item) => (
          <li key={item.href} className="max-w-28 min-w-0 flex-1 sm:max-w-none sm:flex-none">
            <a href={item.href} aria-current={item.current ? 'page' : undefined} className={LINK}>
              {item.icon}
              <span>{item.label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
