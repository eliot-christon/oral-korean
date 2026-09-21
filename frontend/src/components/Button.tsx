import type { ComponentProps } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'subtle'

type ButtonProps = ComponentProps<'button'> & {
  variant?: ButtonVariant
  /** The large round, icon-only form. Name it with `aria-label`. */
  round?: boolean
}

const BASE =
  'inline-flex shrink-0 items-center justify-center gap-2 rounded-full font-bold ' +
  'transition-colors duration-150 select-none cursor-pointer ' +
  'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
  'motion-safe:enabled:active:translate-y-px ' +
  'disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-surface shadow-glow enabled:hover:bg-primary-strong',
  secondary: 'bg-accent text-ink shadow-soft enabled:hover:bg-accent-strong',
  subtle: 'text-primary enabled:hover:bg-primary-soft',
}

const SIZE = 'min-h-12 min-w-12 px-6 text-base'
const ROUND = 'size-16'

/** A native `<button>`: roles, names and keyboard behaviour stay the browser's. */
export function Button({
  variant = 'primary',
  round = false,
  type = 'button',
  className,
  ...props
}: ButtonProps) {
  const classes = `${BASE} ${VARIANTS[variant]} ${round ? ROUND : SIZE} ${className ?? ''}`
  return <button type={type} className={classes.trim()} {...props} />
}
