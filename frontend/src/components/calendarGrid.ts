/**
 * The calendar's pure maths: month lengths, the Sunday-first grid, month and day stepping.
 *
 * Months are 1 to 12 at every boundary of this module. JavaScript's 0-based month is confined
 * to the two `Date` constructions below, and every `Date` is built from year, month and day
 * numbers in local time, never parsed from an ISO string (`new Date('2026-09-21')` is UTC
 * midnight, the 20th west of Greenwich).
 */

/** A displayed month: a year and a month, 1 to 12. */
export type YearMonth = { year: number; month: number }

/** A calendar day, month 1 to 12. */
export type Day = YearMonth & { day: number }

/** The years a calendar may show, both ends included. */
export type YearRange = { minimum: number; maximum: number }

export const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const

/** Sunday first, the Korean convention. */
export const WEEKDAYS = [
  ['Sun', 'Sunday'],
  ['Mon', 'Monday'],
  ['Tue', 'Tuesday'],
  ['Wed', 'Wednesday'],
  ['Thu', 'Thursday'],
  ['Fri', 'Friday'],
  ['Sat', 'Saturday'],
] as const

function localDate(year: number, month: number, day: number): Date {
  const date = new Date(2000, month - 1, day)
  // Set separately: the constructor maps years 0 to 99 onto 1900 to 1999.
  date.setFullYear(year, month - 1, day)
  return date
}

function toDay(date: Date): Day {
  return { year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate() }
}

export function monthName(month: number): string {
  return MONTH_NAMES[month - 1]
}

/** The number of days in `month` of `year`, leap years included. */
export function daysInMonth(year: number, month: number): number {
  // Day 0 of the next month is the last day of this one.
  return localDate(year, month + 1, 0).getDate()
}

/** The weekday the month starts on, 0 for Sunday to 6 for Saturday. */
export function firstWeekday(year: number, month: number): number {
  return localDate(year, month, 1).getDay()
}

/** The month as rows of seven cells, Sunday first: a day number, or `null` for a blank. */
export function monthGrid(year: number, month: number): (number | null)[][] {
  const cells: (number | null)[] = Array.from({ length: firstWeekday(year, month) }, () => null)
  for (let day = 1; day <= daysInMonth(year, month); day += 1) {
    cells.push(day)
  }
  while (cells.length % 7 !== 0) {
    cells.push(null)
  }
  return Array.from({ length: cells.length / 7 }, (_, row) => cells.slice(row * 7, row * 7 + 7))
}

function inRange(year: number, range: YearRange): boolean {
  return year >= range.minimum && year <= range.maximum
}

/** The month `delta` months away, or `null` when it falls outside `range`. */
export function stepMonth(shown: YearMonth, delta: number, range: YearRange): YearMonth | null {
  const index = shown.year * 12 + (shown.month - 1) + delta
  const next = { year: Math.floor(index / 12), month: (index % 12) + 1 }
  return inRange(next.year, range) ? next : null
}

/** The month `delta` months away, wrapping within the same year (December then January). */
export function wrapMonth(shown: YearMonth, delta: number): YearMonth {
  return { year: shown.year, month: ((((shown.month - 1 + delta) % 12) + 12) % 12) + 1 }
}

/** `day` moved into `target`, its day of the month clamped to the target's length. */
export function clampInto(day: number, target: YearMonth): Day {
  return { ...target, day: Math.min(day, daysInMonth(target.year, target.month)) }
}

/** The day `delta` days away, crossing months and years as the calendar does. */
export function addDays(from: Day, delta: number): Day {
  return toDay(localDate(from.year, from.month, from.day + delta))
}

/** The same day moved into the same year: how a yearless calendar wraps past December. */
export function withinYear(day: Day, year: number): Day {
  return day.year === year ? day : clampInto(day.day, { year, month: day.month })
}

export function sameDay(a: Day, b: Day): boolean {
  return a.year === b.year && a.month === b.month && a.day === b.day
}

export function dayInRange(day: Day, range: YearRange): boolean {
  return inRange(day.year, range)
}
