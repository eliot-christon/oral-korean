/**
 * Turns the backend's figures into words for reading, and the tag field into the list the
 * backend expects. Pure, and handed "now" rather than reading the clock, so each case is a
 * table row. Nothing here computes a figure: the score, the recall, whether a word is due and
 * what a familiarity level seeds all arrive from the backend.
 */

import type { Familiarity, FamiliarityLevel, Grade } from './api'

// Records, so a level or grade added to the union without a label here fails to compile.
const FAMILIARITY_LABELS: Record<Familiarity, string> = {
  new: 'New',
  a_little: 'A little',
  well: 'Well',
  very_well: 'Very well',
}

const GRADE_LABELS: Record<Grade, string> = {
  again: 'Again',
  hard: 'Hard',
  good: 'Good',
  easy: 'Easy',
}

export function familiarityLabel(familiarity: Familiarity): string {
  return FAMILIARITY_LABELS[familiarity]
}

export function gradeLabel(grade: Grade): string {
  return GRADE_LABELS[grade]
}

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'always' })

/** A score, or "New" for a word never reviewed: a new word has no score, never 0%. */
export function formatScore(score: number | null): string {
  return score === null ? 'New' : formatPercent(score)
}

export function formatPercent(percent: number): string {
  return `${percent}%`
}

/**
 * How far ahead `date` is, from `now`: "in 1 hour", "in 3 days". Days up to two months, so
 * a review 40 days out reads "in 40 days" rather than a rounded "in 1 month". A moment
 * already reached reads "due now".
 */
export function formatTimeUntil(date: string, now: Date): string {
  const ahead = new Date(date).getTime() - now.getTime()
  if (ahead <= 0) {
    return 'due now'
  }
  if (ahead < HOUR_MS) {
    return RELATIVE.format(Math.max(1, Math.round(ahead / MINUTE_MS)), 'minute')
  }
  if (ahead < DAY_MS) {
    return RELATIVE.format(Math.round(ahead / HOUR_MS), 'hour')
  }
  if (ahead < 60 * DAY_MS) {
    return RELATIVE.format(Math.round(ahead / DAY_MS), 'day')
  }
  if (ahead < 365 * DAY_MS) {
    return RELATIVE.format(Math.round(ahead / (30 * DAY_MS)), 'month')
  }
  return RELATIVE.format(Math.round(ahead / (365 * DAY_MS)), 'year')
}

/**
 * When a word is due, as the list shows it: nothing for a new word (it is learned, not
 * reviewed), "due now" when the backend says it is due, otherwise how far ahead.
 */
export function formatDue(
  statistics: { due: boolean; next_review: string | null },
  now: Date,
): string | null {
  if (statistics.next_review === null) {
    return null
  }
  return statistics.due ? 'due now' : formatTimeUntil(statistics.next_review, now)
}

/** A date and time in the reader's own time zone, or in `timeZone` (for tests). */
export function formatDateTime(date: string, timeZone?: string): string {
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(
    new Date(date),
  )
}

function oneDecimal(value: number): number {
  return Math.round(value * 10) / 10
}

/** A number of days with one decimal: FSRS stability is fractional, "2.3 days". */
export function formatDays(days: number): string {
  const rounded = oneDecimal(days)
  return `${rounded} ${rounded === 1 ? 'day' : 'days'}`
}

/** A difficulty, which FSRS keeps between 1 and 10: "2.1 out of 10". */
export function formatDifficulty(difficulty: number): string {
  return `${oneDecimal(difficulty)} out of 10`
}

/**
 * What adding a word at `level` means, in the backend's own figures: "Well: starts at 20%,
 * first review in about 2 days". The delay is the unfuzzed one, which the real seeding may
 * move by a day or two, hence "about".
 */
export function familiarityOption(level: FamiliarityLevel): string {
  const label = familiarityLabel(level.familiarity)
  if (level.score === null || level.first_review_in_days === null) {
    return `${label}: not known yet, learned from scratch`
  }
  return (
    `${label}: starts at ${formatPercent(level.score)}, ` +
    `first review in about ${formatDays(level.first_review_in_days)}`
  )
}

/**
 * The tags typed in one comma-separated field (`food, topik 1`), as a list. Only split and
 * trimmed: lowercasing and dropping repeats is the backend's job.
 */
export function tagsFromField(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '')
}

/** A word's tags back in the field's comma-separated form, for editing. */
export function tagsToField(tags: string[]): string {
  return tags.join(', ')
}
