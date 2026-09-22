import type { ComponentProps } from 'react'

/**
 * A native link that reads as one: underlined, in the primary colour, with a 48 px touch
 * target. For a link standing on its own line (back to a list, back home), not inside text.
 * `className` places it (in a flex column, `self-start` keeps it from stretching).
 */
export function TextLink({ className, ...props }: ComponentProps<'a'>) {
  const classes =
    'inline-flex min-h-12 items-center gap-2 rounded-full px-4 font-bold text-primary ' +
    'underline underline-offset-4 transition-colors duration-150 hover:bg-primary-soft ' +
    'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
    (className ?? '')
  return <a className={classes.trim()} {...props} />
}
