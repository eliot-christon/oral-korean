import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import { Button } from './Button'
import {
  WEEKDAYS,
  addDays,
  clampInto,
  dayInRange,
  monthGrid,
  monthName,
  stepMonth,
  withinYear,
  wrapMonth,
  type Day,
  type YearMonth,
  type YearRange,
} from './calendarGrid'
import { Field } from './Field'
import { ChevronDownIcon } from './icons'

/** A picked day, month 1 to 12; `year` is `null` when the year is not asked. */
export type CalendarValue = { year: number | null; month: number; day: number }

type CalendarPickerProps = {
  value: CalendarValue | null
  onChange: (value: CalendarValue) => void
  /**
   * With the year: the years the calendar may show, offered in a year control. `null`: the
   * year is not asked, so none is shown, selectable or reported, and months wrap within
   * the year of `initialMonth`, which only lays the grid out.
   */
  yearRange: YearRange | null
  /** The month it opens on. Remount the calendar (a new `key`) to open it afresh. */
  initialMonth: YearMonth
}

// Keys that move the focused day, and by how much: days, or whole months.
const DAY_KEYS: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
const MONTH_KEYS: Record<string, number> = { PageUp: -1, PageDown: 1 }

function dayLabel(day: Day, withYear: boolean): string {
  const label = `${day.day} ${monthName(day.month)}`
  return withYear ? `${label} ${day.year}` : label
}

/**
 * A calendar day picker: tap or click a day, browse with the month buttons (and, when the
 * year is asked, a native year control), or use the keyboard on the grid after the WAI-ARIA
 * date-picker pattern - arrows by a day or a week, Page Up and Page Down by a month, Enter or
 * Space to pick. Controlled: it holds no question, calls no API, and reports every pick
 * through `onChange`. Nothing in it is Hangul: a month header reading 유월 would let the ear's
 * work be done by the eye.
 */
export function CalendarPicker({ value, onChange, yearRange, initialMonth }: CalendarPickerProps) {
  const withYear = yearRange !== null
  const [focused, setFocused] = useState<Day>(() => ({ ...initialMonth, day: 1 }))
  const moveFocus = useRef(false)
  const grid = useRef<HTMLTableElement>(null)

  useEffect(() => {
    if (moveFocus.current) {
      moveFocus.current = false
      grid.current?.querySelector<HTMLButtonElement>(`[data-day="${focused.day}"]`)?.focus()
    }
  }, [focused])

  function shownMonth(delta: number): YearMonth | null {
    return yearRange === null ? wrapMonth(focused, delta) : stepMonth(focused, delta, yearRange)
  }

  function allowed(day: Day): Day | null {
    if (yearRange === null) {
      return withinYear(day, initialMonth.year)
    }
    return dayInRange(day, yearRange) ? day : null
  }

  function pick(day: Day): void {
    setFocused(day)
    onChange({ year: withYear ? day.year : null, month: day.month, day: day.day })
  }

  // From the day the key was pressed on: a screen reader can focus any day, not only the
  // grid's tab stop.
  function handleKey(from: Day, event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      pick(from)
      return
    }
    let next: Day | null = null
    if (event.key in DAY_KEYS) {
      next = allowed(addDays(from, DAY_KEYS[event.key]))
    } else if (event.key in MONTH_KEYS) {
      const month = shownMonth(MONTH_KEYS[event.key])
      next = month === null ? null : clampInto(from.day, month)
    } else {
      return
    }
    event.preventDefault()
    if (next !== null) {
      moveFocus.current = true
      setFocused(next)
    }
  }

  const previous = shownMonth(-1)
  const following = shownMonth(1)
  const heading = withYear ? `${monthName(focused.month)} ${focused.year}` : monthName(focused.month)
  const isSelected = (day: number) =>
    value !== null &&
    value.month === focused.month &&
    value.day === day &&
    (withYear ? value.year === focused.year : value.year === null)

  return (
    <div className="flex w-full max-w-sm flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <Button
          variant="subtle"
          className="px-3"
          aria-label="Previous month"
          disabled={previous === null}
          onClick={() => previous !== null && setFocused(clampInto(focused.day, previous))}
        >
          <ChevronDownIcon className="size-6 rotate-90" />
        </Button>
        <p id="calendar-heading" aria-live="polite" className="font-display text-2xl text-ink tabular-nums">
          {heading}
        </p>
        <Button
          variant="subtle"
          className="px-3"
          aria-label="Next month"
          disabled={following === null}
          onClick={() => following !== null && setFocused(clampInto(focused.day, following))}
        >
          <ChevronDownIcon className="size-6 -rotate-90" />
        </Button>
      </div>

      {yearRange !== null && (
        <Field
          as="select"
          label="Year"
          value={focused.year}
          onChange={(event) =>
            setFocused(clampInto(focused.day, { year: Number(event.target.value), month: focused.month }))
          }
        >
          {Array.from({ length: yearRange.maximum - yearRange.minimum + 1 }, (_, index) => {
            const year = yearRange.minimum + index
            return (
              <option key={year} value={year}>
                {year}
              </option>
            )
          })}
        </Field>
      )}

      <table ref={grid} role="grid" aria-labelledby="calendar-heading" className="w-full table-fixed">
        <thead>
          <tr>
            {WEEKDAYS.map(([short, full]) => (
              <th key={short} scope="col" abbr={full} className="pb-1 text-sm font-bold text-muted">
                {short}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthGrid(focused.year, focused.month).map((week, row) => (
            <tr key={row}>
              {week.map((day, column) => (
                <td key={column} className="p-0.5 text-center">
                  {day !== null && (
                    <button
                      type="button"
                      data-day={day}
                      aria-label={dayLabel({ ...focused, day }, withYear)}
                      aria-pressed={isSelected(day)}
                      tabIndex={day === focused.day ? 0 : -1}
                      onClick={() => pick({ ...focused, day })}
                      onKeyDown={(event) => handleKey({ ...focused, day }, event)}
                      className={
                        'mx-auto flex size-11 cursor-pointer items-center justify-center rounded-full ' +
                        'text-base font-bold tabular-nums transition-colors duration-150 ' +
                        'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary ' +
                        (isSelected(day)
                          ? 'bg-primary text-surface shadow-glow'
                          : 'text-ink hover:bg-primary-soft')
                      }
                    >
                      {day}
                    </button>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
