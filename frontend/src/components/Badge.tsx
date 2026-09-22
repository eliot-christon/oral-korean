import type { ReactNode } from 'react'

export type BadgeTone = 'tag' | 'score' | 'highlight'

const TONES: Record<BadgeTone, string> = {
  tag: 'bg-primary-soft text-primary',
  score: 'bg-primary text-surface',
  highlight: 'bg-accent text-ink',
}

/**
 * A short label in a pill: a tag, a score, "New", "due now". The words carry the meaning;
 * the tone only groups them by kind, so colour is never the only signal.
 */
export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return (
    <span
      data-tone={tone}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-sm font-bold ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}
