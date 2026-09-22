/**
 * Tests for the word list (vocab-words-ui T02, and T03 for its add links and notice), against
 * the tickets' test contracts.
 *
 * `fetch` is stubbed with responses shaped like the vocabulary routes'
 * (`src/oral_korean/api/routes/vocab_words.py`, pinned by `tests/test_api_vocab_words.py`).
 * Only `Date` is faked, at a fixed "now", so "in 3 days" is exact while promises and
 * Testing Library's timers run for real. Same conventions as `NumbersPage.test.tsx`:
 * explicit `cleanup()`, no jest-dom matcher.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { leaveNotice } from '../notice'
import { jsonResponse, wordStub } from '../testUtils'
import { WordsPage } from './WordsPage'

const NOW = new Date('2026-09-22T10:00:00Z')
const DAY_MS = 24 * 3_600_000

function inDays(days: number): string {
  return new Date(NOW.getTime() + days * DAY_MS).toISOString()
}

function reviewed(score: number, due: boolean, nextReview: string): Record<string, unknown> {
  return {
    score,
    recall: 90,
    stability: 4.2,
    difficulty: 5.1,
    phase: 'review',
    next_review: nextReview,
    last_review: '2026-09-20T10:00:00Z',
    due,
    review_count: 2,
    lapse_count: 0,
  }
}

const NEW_WORD = wordStub({ id: 1, korean: '사과', translations: ['apple', 'pomme'], tags: ['food'] })
const DUE_WORD = wordStub({
  id: 2,
  korean: '학교',
  translations: ['school'],
  familiarity: 'well',
  statistics: reviewed(20, true, inDays(-1)),
})
const LATER_WORD = wordStub({
  id: 3,
  korean: '물',
  translations: ['water'],
  tags: ['food', 'drinks'],
  familiarity: 'very_well',
  statistics: reviewed(64, false, inDays(3)),
})

const FULL_LIST = {
  words: [NEW_WORD, DUE_WORD, LATER_WORD],
  summary: { total: 3, new: 1, due: 1, average_score: 42 },
}

const FOOD_LIST = {
  words: [NEW_WORD],
  summary: { total: 1, new: 1, due: 0, average_score: null },
}

const TAGS = { tags: [{ tag: 'drinks', count: 1 }, { tag: 'food', count: 2 }] }

interface StubConfig {
  /** The tags route's body. */
  tags?: unknown
  /** The unfiltered list; a `tag` query answers `byTag[tag]`. */
  list?: unknown
  byTag?: Record<string, unknown>
  /** A refusal for every list request: its status and body. */
  listFails?: { status: number; body: unknown }
}

function stubFetch(config: StubConfig = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    if (url.pathname === '/api/vocab/tags') {
      return Promise.resolve(jsonResponse(config.tags ?? TAGS))
    }
    if (url.pathname === '/api/vocab/words') {
      if (config.listFails) {
        return Promise.resolve(jsonResponse(config.listFails.body, config.listFails.status))
      }
      const tag = url.searchParams.get('tag')
      return Promise.resolve(jsonResponse(tag === null ? (config.list ?? FULL_LIST) : config.byTag?.[tag]))
    }
    throw new Error(`Unhandled fetch in test: ${url.pathname}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The query string of every list request, in order (`''` for no filter). */
function listQueries(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls
    .map((call) => new URL(String(call[0]), 'http://localhost'))
    .filter((url) => url.pathname === '/api/vocab/words')
    .map((url) => url.search)
}

async function cards(): Promise<HTMLElement[]> {
  const list = await screen.findByRole('list')
  return within(list).getAllByRole('listitem')
}

function cardFor(korean: string, all: HTMLElement[]): HTMLElement {
  const card = all.find((item) => item.textContent?.includes(korean))
  if (card === undefined) {
    throw new Error(`no card for ${korean}`)
  }
  return card
}

/** The value shown under a summary label ("Words", "Average score", ...). */
function summaryValue(label: string): string | null {
  const term = screen.getByText(label, { selector: 'dt' })
  return term.parentElement?.querySelector('dd')?.textContent ?? null
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('one card per word: New for a word never reviewed, due now, and in 3 days', async () => {
  stubFetch()

  render(<WordsPage />)

  const all = await cards()
  expect(all).toHaveLength(3)
  const newCard = cardFor('사과', all)
  expect(newCard.textContent).toContain('New')
  expect(newCard.textContent).not.toContain('0%')
  expect(newCard.textContent).toContain('apple; pomme')
  expect(cardFor('학교', all).textContent).toContain('due now')
  expect(cardFor('학교', all).textContent).toContain('20%')
  expect(cardFor('물', all).textContent).toContain('in 3 days')
  expect(cardFor('물', all).textContent).toContain('64%')
})

test('a new word shows no due text at all', async () => {
  stubFetch()

  render(<WordsPage />)

  const newCard = cardFor('사과', await cards())
  expect(newCard.textContent).not.toMatch(/due|review/i)
})

test('the summary shows the totals the backend computed', async () => {
  stubFetch()

  render(<WordsPage />)
  await cards()

  expect(summaryValue('Words')).toBe('3')
  expect(summaryValue('New')).toBe('1')
  expect(summaryValue('Due now')).toBe('1')
  expect(summaryValue('Average score')).toBe('42%')
})

test('a null average score shows a dash, not 0%', async () => {
  stubFetch({ list: FOOD_LIST })

  render(<WordsPage />)
  await cards()

  expect(summaryValue('Average score')).toBe('-')
})

test('choosing a tag reloads the list for it, and clearing the filter shows every word again', async () => {
  const fetchMock = stubFetch({ byTag: { food: FOOD_LIST } })

  render(<WordsPage />)
  expect(await cards()).toHaveLength(3)
  const filter = (await screen.findByRole('combobox', { name: 'Tag' })) as HTMLSelectElement
  expect(within(filter).getAllByRole('option').map((option) => option.textContent)).toEqual([
    'All tags',
    'drinks (1)',
    'food (2)',
  ])

  fireEvent.change(filter, { target: { value: 'food' } })

  await waitFor(() => expect(listQueries(fetchMock)).toEqual(['', '?tag=food']))
  await waitFor(async () => expect(await cards()).toHaveLength(1))
  expect((await cards())[0].textContent).toContain('사과')
  expect(summaryValue('Words')).toBe('1')

  fireEvent.change(filter, { target: { value: '' } })

  await waitFor(() => expect(listQueries(fetchMock)).toEqual(['', '?tag=food', '']))
  await waitFor(async () => expect(await cards()).toHaveLength(3))
})

test('a tag with characters that need escaping is sent encoded', async () => {
  const tag = 'topik 1 & 2'
  const fetchMock = stubFetch({ tags: { tags: [{ tag, count: 1 }] }, byTag: { [tag]: FOOD_LIST } })

  render(<WordsPage />)
  fireEvent.change(await screen.findByRole('combobox', { name: 'Tag' }), { target: { value: tag } })

  await waitFor(() => expect(listQueries(fetchMock)).toEqual(['', '?tag=topik+1+%26+2']))
})

test('each card links to its word', async () => {
  stubFetch()

  render(<WordsPage />)

  const all = await cards()
  expect(within(cardFor('물', all)).getByRole('link').getAttribute('href')).toBe('#/words/3')
  expect(within(cardFor('사과', all)).getByRole('link').getAttribute('href')).toBe('#/words/1')
})

test('an empty vocabulary shows the empty state, not an empty list', async () => {
  stubFetch({ list: { words: [], summary: { total: 0, new: 0, due: 0, average_score: null } } })

  render(<WordsPage />)

  expect(await screen.findByText(/no words yet/i)).toBeDefined()
  expect(screen.queryByRole('list')).toBeNull()
})

test('a failed list request shows the backends own message in an alert', async () => {
  stubFetch({ listFails: { status: 500, body: { detail: 'The vocabulary database is newer than this app.' } } })

  render(<WordsPage />)

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe('The vocabulary database is newer than this app.')
  // Not a blank page: the heading is still there.
  expect(screen.getByRole('heading', { name: 'Words' })).toBeDefined()
})

test('a list request that cannot reach the backend shows an alert', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
  )

  render(<WordsPage />)

  await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
  expect(screen.getAllByRole('alert')[0].textContent).toMatch(/could not reach the backend/i)
})

test('Korean text is marked as Korean', async () => {
  stubFetch()

  render(<WordsPage />)

  const all = await cards()
  for (const [korean, card] of [['사과', cardFor('사과', all)], ['학교', cardFor('학교', all)]] as const) {
    const marked = card.querySelector('[lang="ko"]')
    expect(marked?.textContent).toBe(korean)
  }
})

test('the list links to the add page', async () => {
  stubFetch()

  render(<WordsPage />)
  await cards()

  expect(screen.getByRole('link', { name: 'Add words' }).getAttribute('href')).toBe('#/words/new')
})

test('the empty state links to the add page too', async () => {
  stubFetch({ list: { words: [], summary: { total: 0, new: 0, due: 0, average_score: null } } })

  render(<WordsPage />)

  const link = await screen.findByRole('link', { name: /add your first words/i })
  expect(link.getAttribute('href')).toBe('#/words/new')
})

test('a notice left by the page before is shown once, then gone', async () => {
  stubFetch()
  leaveNotice('Added 2 words.')

  render(<WordsPage />)
  await cards()
  expect(screen.getByRole('status').textContent).toBe('Added 2 words.')
  cleanup()

  render(<WordsPage />)
  await cards()
  expect(screen.queryByRole('status')).toBeNull()
})
