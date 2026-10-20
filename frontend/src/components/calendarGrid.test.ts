/**
 * The calendar's pure maths (date-exercise T03): month lengths, the Sunday-first grid and
 * month stepping, with months 1 to 12 in and out. No DOM.
 */

import { describe, expect, it } from 'vitest'

import { addDays, clampInto, daysInMonth, firstWeekday, monthGrid, stepMonth, wrapMonth } from './calendarGrid'

const WINDOW = { minimum: 1950, maximum: 2049 }

describe('month lengths', () => {
  it.each([
    [2024, 2, 29],
    [2026, 2, 28],
    [2000, 2, 29],
    [1900, 2, 28],
    [2026, 4, 30],
    [2026, 12, 31],
  ])('%i-%i has %i days', (year, month, days) => {
    expect(daysInMonth(year, month)).toBe(days)
  })
})

describe('the grid, Sunday first', () => {
  function blanksBeforeTheFirst(year: number, month: number): number {
    return monthGrid(year, month)[0].indexOf(1)
  }

  function days(year: number, month: number): number[] {
    return monthGrid(year, month)
      .flat()
      .filter((cell): cell is number => cell !== null)
  }

  it('starts September 2026 on a Tuesday, after 2 blanks, with 30 days', () => {
    expect(firstWeekday(2026, 9)).toBe(2)
    expect(blanksBeforeTheFirst(2026, 9)).toBe(2)
    expect(days(2026, 9)).toEqual(Array.from({ length: 30 }, (_, index) => index + 1))
  })

  it('starts February 2026 on a Sunday, with no blank and exactly 4 rows', () => {
    expect(blanksBeforeTheFirst(2026, 2)).toBe(0)
    expect(days(2026, 2)).toHaveLength(28)
    expect(monthGrid(2026, 2)).toHaveLength(4)
  })

  it('starts October 2026 on a Thursday, after 4 blanks, with 31 days', () => {
    expect(blanksBeforeTheFirst(2026, 10)).toBe(4)
    expect(days(2026, 10)).toHaveLength(31)
  })

  it('always lays out whole weeks', () => {
    for (let month = 1; month <= 12; month += 1) {
      expect(monthGrid(2026, month).every((week) => week.length === 7)).toBe(true)
    }
  })
})

describe('month stepping, 1-based', () => {
  it('steps September to October, month 10', () => {
    expect(stepMonth({ year: 2026, month: 9 }, 1, WINDOW)).toEqual({ year: 2026, month: 10 })
  })

  it('crosses year boundaries both ways', () => {
    expect(stepMonth({ year: 2026, month: 12 }, 1, WINDOW)).toEqual({ year: 2027, month: 1 })
    expect(stepMonth({ year: 2026, month: 1 }, -1, WINDOW)).toEqual({ year: 2025, month: 12 })
  })

  it('stops at the ends of the window', () => {
    expect(stepMonth({ year: 2049, month: 12 }, 1, WINDOW)).toBeNull()
    expect(stepMonth({ year: 1950, month: 1 }, -1, WINDOW)).toBeNull()
  })

  it('wraps within the reference year when there is no year', () => {
    expect(wrapMonth({ year: 2026, month: 12 }, 1)).toEqual({ year: 2026, month: 1 })
    expect(wrapMonth({ year: 2026, month: 1 }, -1)).toEqual({ year: 2026, month: 12 })
  })
})

describe('day stepping', () => {
  it('crosses into the next month', () => {
    expect(addDays({ year: 2026, month: 9, day: 30 }, 1)).toEqual({ year: 2026, month: 10, day: 1 })
    expect(addDays({ year: 2026, month: 2, day: 28 }, 7)).toEqual({ year: 2026, month: 3, day: 7 })
  })

  it('clamps a day into a shorter month', () => {
    expect(clampInto(31, { year: 2026, month: 11 })).toEqual({ year: 2026, month: 11, day: 30 })
  })
})
