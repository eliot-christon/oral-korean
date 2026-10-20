/**
 * The calendar day picker (date-exercise T03), against the ticket's test contract.
 *
 * Same conventions as `ClockFace.test.tsx`: `cleanup()` explicit, no jest-dom, no
 * `user-event`. The calendar is controlled, so picks are read from the last `onChange` call.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CalendarPicker, type CalendarValue } from './CalendarPicker'

afterEach(() => {
  cleanup()
})

const WINDOW = { minimum: 1950, maximum: 2049 }
const HANGUL = /[가-힣]/

function renderCalendar(
  initialMonth: { year: number; month: number },
  { withYear = true, value = null }: { withYear?: boolean; value?: CalendarValue | null } = {},
) {
  const onChange = vi.fn<(value: CalendarValue) => void>()
  const view = render(
    <CalendarPicker
      value={value}
      onChange={onChange}
      yearRange={withYear ? WINDOW : null}
      initialMonth={initialMonth}
    />,
  )
  return { ...view, onChange }
}

function lastPick(onChange: ReturnType<typeof renderCalendar>['onChange']): CalendarValue {
  const call = onChange.mock.calls.at(-1)
  if (call === undefined) {
    throw new Error('onChange was never called')
  }
  return call[0]
}

function heading(): string {
  return document.getElementById('calendar-heading')?.textContent ?? ''
}

function dayButtons(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('button[data-day]'))
}

function next(): void {
  fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
}

function focusedName(): string | null {
  return document.activeElement?.getAttribute('aria-label') ?? null
}

function press(name: string, key: string): void {
  const day = screen.getByRole('button', { name })
  day.focus()
  fireEvent.keyDown(day, { key })
}

describe('with the year, bounds 1950-2049', () => {
  it('shows September 2026 with 30 enabled days', () => {
    renderCalendar({ year: 2026, month: 9 })

    expect(heading()).toBe('September 2026')
    expect(dayButtons().filter((button) => !button.disabled)).toHaveLength(30)
  })

  it('reports a click with a 1-based month', () => {
    const { onChange } = renderCalendar({ year: 2026, month: 9 })

    fireEvent.click(screen.getByRole('button', { name: '21 September 2026' }))

    expect(lastPick(onChange)).toEqual({ year: 2026, month: 9, day: 21 })
  })

  it('navigates across years', () => {
    renderCalendar({ year: 2026, month: 12 })
    next()
    expect(heading()).toBe('January 2027')

    cleanup()
    renderCalendar({ year: 2026, month: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
    expect(heading()).toBe('December 2025')
  })

  it('disables navigation at the ends of the window', () => {
    renderCalendar({ year: 2049, month: 12 })
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Next month' }).disabled).toBe(true)

    cleanup()
    renderCalendar({ year: 1950, month: 1 })
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Previous month' }).disabled).toBe(true)
  })

  it('offers exactly the window years, and choosing one keeps the month', () => {
    renderCalendar({ year: 2026, month: 9 })
    const year = screen.getByRole<HTMLSelectElement>('combobox', { name: 'Year' })

    expect(Array.from(year.options, (option) => Number(option.value))).toEqual(
      Array.from({ length: 100 }, (_, index) => 1950 + index),
    )
    fireEvent.change(year, { target: { value: '1988' } })
    expect(heading()).toBe('September 1988')
  })

  it('shows 29 days in February 2024 and 28 in February 2026', () => {
    renderCalendar({ year: 2024, month: 2 })
    expect(dayButtons()).toHaveLength(29)

    cleanup()
    renderCalendar({ year: 2026, month: 2 })
    expect(dayButtons()).toHaveLength(28)
  })

  it('marks the selected day pressed, and no other', () => {
    renderCalendar({ year: 2026, month: 9 }, { value: { year: 2026, month: 9, day: 21 } })

    const pressed = dayButtons().filter((button) => button.getAttribute('aria-pressed') === 'true')
    expect(pressed.map((button) => button.getAttribute('aria-label'))).toEqual(['21 September 2026'])
  })

  it('does not mark the same day of another year', () => {
    renderCalendar({ year: 2026, month: 9 }, { value: { year: 2025, month: 9, day: 21 } })

    expect(dayButtons().some((button) => button.getAttribute('aria-pressed') === 'true')).toBe(false)
  })
})

describe('without the year, reference year 2026', () => {
  it('shows no year control and no year anywhere', () => {
    const { container } = renderCalendar({ year: 2026, month: 9 }, { withYear: false })
    // Every text node and every name on its own: the day numbers run together in
    // `textContent`, where "2021" would be the 20th and the 21st.
    const texts = [
      ...Array.from(container.querySelectorAll('*'), (element) =>
        Array.from(element.childNodes, (node) => (node.nodeType === Node.TEXT_NODE ? node.textContent : '')).join(''),
      ),
      ...dayButtons().map((button) => button.getAttribute('aria-label') ?? ''),
    ]

    expect(screen.queryByRole('combobox')).toBeNull()
    expect(heading()).toBe('September')
    expect(texts.filter((text) => text.includes('2026'))).toEqual([])
  })

  it('reports a click with a null year', () => {
    const { onChange } = renderCalendar({ year: 2026, month: 9 }, { withYear: false })

    fireEvent.click(screen.getByRole('button', { name: '21 September' }))

    expect(lastPick(onChange)).toEqual({ year: null, month: 9, day: 21 })
  })

  it('wraps from December to January, still without a year', () => {
    renderCalendar({ year: 2026, month: 12 }, { withYear: false })

    next()

    expect(heading()).toBe('January')
  })

  it('wraps the keyboard past the end of the year too', () => {
    renderCalendar({ year: 2026, month: 12 }, { withYear: false })
    press('31 December', 'PageDown')
    press('31 January', 'ArrowRight')

    expect(focusedName()).toBe('1 February')
  })
})

describe('no Hangul', () => {
  it.each([true, false])('never shows Hangul through all twelve months (with year: %s)', (withYear) => {
    const { container } = renderCalendar({ year: 2026, month: 1 }, { withYear })

    for (let month = 1; month <= 12; month += 1) {
      expect(container.textContent).not.toMatch(HANGUL)
      next()
    }
  })
})

describe('keyboard, with the year', () => {
  it('crosses into the next month with Arrow Right', () => {
    renderCalendar({ year: 2026, month: 9 })

    press('30 September 2026', 'ArrowRight')

    expect(focusedName()).toBe('1 October 2026')
    expect(heading()).toBe('October 2026')
  })

  it('moves a week with Arrow Down', () => {
    renderCalendar({ year: 2026, month: 2 })

    press('28 February 2026', 'ArrowDown')

    expect(focusedName()).toBe('7 March 2026')
  })

  it('moves a month with Page Down and back with Page Up', () => {
    renderCalendar({ year: 2026, month: 9 })

    press('21 September 2026', 'PageDown')
    expect(focusedName()).toBe('21 October 2026')
    expect(heading()).toBe('October 2026')

    press('21 October 2026', 'PageUp')
    expect(focusedName()).toBe('21 September 2026')
  })

  it('clamps the focus into a shorter month, picking nothing', () => {
    const { onChange } = renderCalendar({ year: 2026, month: 10 })

    press('31 October 2026', 'PageDown')

    expect(focusedName()).toBe('30 November 2026')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('stops at the start of the window', () => {
    renderCalendar({ year: 1950, month: 1 })

    press('1 January 1950', 'ArrowLeft')

    expect(focusedName()).toBe('1 January 1950')
    expect(heading()).toBe('January 1950')
  })

  it.each(['Enter', ' '])('picks the focused day with %j', (key) => {
    const { onChange } = renderCalendar({ year: 2026, month: 9 })

    press('21 September 2026', key)

    expect(lastPick(onChange)).toEqual({ year: 2026, month: 9, day: 21 })
  })

  it('keeps a single tab stop in the grid', () => {
    renderCalendar({ year: 2026, month: 9 })

    expect(dayButtons().filter((button) => button.tabIndex === 0)).toHaveLength(1)
  })
})
