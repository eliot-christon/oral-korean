import type { ReactNode } from 'react'

import { AlertIcon, CheckIcon, CrossIcon, EyeIcon } from './icons'

export type FeedbackTone = 'success' | 'error' | 'warning' | 'neutral'

/**
 * Each tone has its own colours, icon and entrance, so colour is never the only signal.
 * Animations go through `motion-safe:` only: a user who asks for reduced motion gets none.
 */
type ToneStyle = { box: string; badge: string; Icon: (props: { className?: string }) => ReactNode }

const TONES: Record<FeedbackTone, ToneStyle> = {
  success: {
    box: 'bg-success-soft text-success-ink motion-safe:animate-pop',
    badge: 'bg-success text-surface',
    Icon: CheckIcon,
  },
  error: {
    box: 'bg-error-soft text-error-ink motion-safe:animate-shake',
    badge: 'bg-error text-surface',
    Icon: CrossIcon,
  },
  warning: {
    box: 'bg-warning-soft text-warning-ink motion-safe:animate-slide-in',
    badge: 'bg-warning text-ink',
    Icon: AlertIcon,
  },
  neutral: {
    box: 'bg-primary-soft text-ink motion-safe:animate-slide-in',
    badge: 'bg-primary text-surface',
    Icon: EyeIcon,
  },
}

/**
 * A verdict or an error message. It adds no words of its own: the caller's `children` are
 * the whole message. `data-tone` names the tone for tests, which cannot see colour.
 */
export function Feedback({
  tone,
  role = 'status',
  children,
}: {
  tone: FeedbackTone
  role?: 'status' | 'alert'
  children: ReactNode
}) {
  const { box, badge, Icon } = TONES[tone]
  return (
    <div
      role={role}
      data-tone={tone}
      className={`flex items-start gap-3 rounded-card p-4 font-semibold ${box}`}
    >
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-full ${badge}`}>
        <Icon />
      </span>
      <div className="min-w-0 self-center">{children}</div>
    </div>
  )
}
