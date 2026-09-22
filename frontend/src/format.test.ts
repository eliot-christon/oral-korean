/**
 * The formatting helper (vocab-words-ui T02, T03), as tables at a fixed "now". Pure.
 */

import { describe, expect, it } from 'vitest'

import {
  familiarityOption,
  formatDateTime,
  formatDays,
  formatDifficulty,
  formatDue,
  formatScore,
  formatTimeUntil,
  tagsFromField,
  tagsToField,
} from './format'

const NOW = new Date('2026-09-22T10:00:00Z')
const HOUR_MS = 3_600_000
const DAY_MS = 24 * HOUR_MS

function ahead(ms: number): string {
  return new Date(NOW.getTime() + ms).toISOString()
}

describe('formatTimeUntil', () => {
  it.each([
    ['now', ahead(0), 'due now'],
    ['a date in the past', ahead(-3 * DAY_MS), 'due now'],
    ['ten minutes ahead', ahead(10 * 60_000), 'in 10 minutes'],
    ['one hour ahead', ahead(HOUR_MS), 'in 1 hour'],
    ['one day ahead', ahead(DAY_MS), 'in 1 day'],
    ['three days ahead', ahead(3 * DAY_MS), 'in 3 days'],
    ['40 days ahead', ahead(40 * DAY_MS), 'in 40 days'],
    ['90 days ahead', ahead(90 * DAY_MS), 'in 3 months'],
    ['two years ahead', ahead(730 * DAY_MS), 'in 2 years'],
  ])('reads %s as %j', (_case, date, text) => {
    expect(formatTimeUntil(date, NOW)).toBe(text)
  })
})

describe('formatDue', () => {
  it('shows nothing for a new word, which has no next review', () => {
    expect(formatDue({ due: false, next_review: null }, NOW)).toBeNull()
  })

  it('follows the backends due flag, not the date', () => {
    // Due by the backend's clock though the date is still ahead by this one's.
    expect(formatDue({ due: true, next_review: ahead(DAY_MS) }, NOW)).toBe('due now')
  })

  it('says how far ahead a word not yet due is', () => {
    expect(formatDue({ due: false, next_review: ahead(3 * DAY_MS) }, NOW)).toBe('in 3 days')
  })
})

describe('formatScore', () => {
  it.each<[number | null, string]>([
    [null, 'New'],
    [0, '0%'],
    [87, '87%'],
    [100, '100%'],
  ])('reads %j as %j', (score, text) => {
    expect(formatScore(score)).toBe(text)
  })
})

describe('the other figures', () => {
  it.each<[number, string]>([
    [2.3065, '2.3 days'],
    [1, '1 day'],
    [0.96, '1 day'],
    [8.2956, '8.3 days'],
  ])('formats a stability of %j as %j', (days, text) => {
    expect(formatDays(days)).toBe(text)
  })

  it('formats a difficulty out of 10', () => {
    expect(formatDifficulty(2.118103970459016)).toBe('2.1 out of 10')
  })

  it('formats a date and time in the given time zone', () => {
    expect(formatDateTime('2026-09-22T10:00:00Z', 'UTC')).toBe('Sep 22, 2026, 10:00 AM')
  })
})

describe('familiarityOption', () => {
  it('says what a level seeds, in the figures the catalogue gave', () => {
    const level = { familiarity: 'well', grade: 'good', score: 20, stability: 2.3, first_review_in_days: 2 } as const
    expect(familiarityOption(level)).toBe('Well: starts at 20%, first review in about 2 days')
  })

  it('follows the catalogue, not a table of its own', () => {
    const level = { familiarity: 'well', grade: 'good', score: 31, stability: 5, first_review_in_days: 5 } as const
    expect(familiarityOption(level)).toBe('Well: starts at 31%, first review in about 5 days')
  })

  it('says a new word starts from nothing', () => {
    const level = { familiarity: 'new', grade: null, score: null, stability: null, first_review_in_days: null } as const
    expect(familiarityOption(level)).toBe('New: not known yet, learned from scratch')
  })
})

describe('the tag field', () => {
  it.each<[string, string[]]>([
    ['food, fruit', ['food', 'fruit']],
    ['  food ,fruit  ', ['food', 'fruit']],
    ['topik 1', ['topik 1']],
    ['food,, ,fruit,', ['food', 'fruit']],
    ['', []],
    ['   ', []],
    // Case and repeats are the backend's to settle.
    ['Food, food', ['Food', 'food']],
  ])('splits %j into %j', (text, tags) => {
    expect(tagsFromField(text)).toEqual(tags)
  })

  it('joins a words tags back for editing', () => {
    expect(tagsToField(['food', 'topik 1'])).toBe('food, topik 1')
    expect(tagsFromField(tagsToField(['food', 'topik 1']))).toEqual(['food', 'topik 1'])
  })
})
