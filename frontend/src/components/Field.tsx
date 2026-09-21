import type { ComponentProps, ReactNode } from 'react'

import { ChevronDownIcon } from './icons'

/**
 * `className` styles the wrapping label (width, placement), not the control: the
 * control's look is the primitive's. Every other prop goes to the native control.
 */
type FieldProps =
  | ({ label: ReactNode; as?: 'input' } & ComponentProps<'input'>)
  | ({ label: ReactNode; as: 'select' } & ComponentProps<'select'>)

// text-base keeps input text at 16px: iOS Safari zooms into anything smaller on focus.
const CONTROL =
  'min-h-12 w-full rounded-field border-2 border-line bg-surface px-4 text-base text-ink ' +
  'transition-colors duration-150 enabled:hover:border-primary focus:border-primary ' +
  'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
  'disabled:cursor-not-allowed disabled:opacity-45'

function FieldLabel({
  label,
  className,
  children,
}: {
  label: ReactNode
  className: string | undefined
  children: ReactNode
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className ?? ''}`.trim()}>
      <span className="text-sm font-bold text-muted">{label}</span>
      {children}
    </label>
  )
}

/** A visible label wrapping a native `<input>` or `<select>`, which it names. */
export function Field(props: FieldProps) {
  if (props.as === 'select') {
    const { label, as: _as, className, ...select } = props
    return (
      <FieldLabel label={label} className={className}>
        <span className="relative block">
          <select className={`${CONTROL} cursor-pointer appearance-none pr-11`} {...select} />
          <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-4 size-5 -translate-y-1/2 text-primary" />
        </span>
      </FieldLabel>
    )
  }
  const { label, as: _as, className, ...input } = props
  return (
    <FieldLabel label={label} className={className}>
      <input className={CONTROL} {...input} />
    </FieldLabel>
  )
}
