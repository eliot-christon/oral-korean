import type { ComponentProps } from 'react'

/** The one surface: a rounded, softly shadowed panel on the page ground. */
export function Card({ className, ...props }: ComponentProps<'div'>) {
  const classes = `rounded-card bg-surface p-5 shadow-card sm:p-8 ${className ?? ''}`
  return <div className={classes.trim()} {...props} />
}
