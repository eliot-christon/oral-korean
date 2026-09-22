/**
 * Tests for one word's page (vocab-words-ui T02, and T03 for editing and deleting), against
 * the tickets' test contracts.
 *
 * `fetch` is stubbed with a word detail shaped like `GET /api/vocab/words/{id}`
 * (`WordDetailResponse` in `src/oral_korean/api/routes/vocab_words.py`). Only `Date` is
 * faked. Same conventions as `NumbersPage.test.tsx`: explicit `cleanup()`, no jest-dom
 * matcher.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { jsonResponse, wordStub } from '../testUtils'
import { WordDetailPage } from './WordDetailPage'

const NOW = new Date('2026-09-26T10:00:00Z')

/** Added as "well" on the 22nd, answered Again on the 24th, then Good on the 25th. */
const REVIEWED_WORD = wordStub({
  id: 7,
  korean: '사과',
  translations: ['apple', 'pomme'],
  tags: ['food'],
  familiarity: 'well',
  added_at: '2026-09-22T10:00:00Z',
  statistics: {
    score: 23,
    recall: 96,
    stability: 3.4051,
    difficulty: 6.2,
    phase: 'review',
    next_review: '2026-09-28T10:00:00Z',
    last_review: '2026-09-25T10:00:00Z',
    due: false,
    review_count: 2,
    lapse_count: 1,
  },
  history: [
    {
      reviewed_at: '2026-09-22T10:00:00Z',
      grade: 'good',
      is_seed: true,
      recall_before: null,
      stability: 2.3065,
      difficulty: 2.1181,
      next_review: '2026-09-24T10:00:00Z',
    },
    {
      reviewed_at: '2026-09-24T10:00:00Z',
      grade: 'again',
      is_seed: false,
      recall_before: 90,
      stability: 0.8,
      difficulty: 6.9,
      next_review: '2026-09-25T10:00:00Z',
    },
    {
      reviewed_at: '2026-09-25T10:00:00Z',
      grade: 'good',
      is_seed: false,
      recall_before: 81,
      stability: 3.4051,
      difficulty: 6.2,
      next_review: '2026-09-28T10:00:00Z',
    },
  ],
})

const NEW_WORD = wordStub({ id: 8, korean: '집', translations: ['house', 'home'], history: [] })

const STATISTIC_LABELS = [
  'Score',
  'Recall',
  'Stability',
  'Difficulty',
  'Next review',
  'Last review',
  'Reviews',
  'Lapses',
  'Added on',
  'Added as',
]

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(body, status)))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** A statistic's row: its label's `<dt>` and the value beside it. */
function statistic(label: string): { term: HTMLElement; value: string } | null {
  const labelSpan = screen.queryByText(label, { selector: 'dt > span' })
  const term = labelSpan?.closest('dt') ?? null
  if (!(term instanceof HTMLElement)) {
    return null
  }
  return { term, value: term.parentElement?.querySelector('dd')?.textContent ?? '' }
}

function historyRows(): HTMLElement[] {
  const history = screen.getByRole('heading', { name: 'History' }).parentElement
  if (history === null) {
    throw new Error('no history section')
  }
  return within(history).getAllByRole('listitem')
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

test('asks for the word its id names', async () => {
  const fetchMock = stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)

  await screen.findByRole('heading', { name: '사과' })
  expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual(['/api/vocab/words/7'])
})

test('shows the word, its translations and its tags, the Korean marked as Korean', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)

  const heading = await screen.findByRole('heading', { level: 1, name: '사과' })
  expect(heading.getAttribute('lang')).toBe('ko')
  expect(screen.getByText('apple; pomme')).toBeDefined()
  expect(screen.getByText('food')).toBeDefined()
})

test('the history lists the seed and both answers, oldest first, the seed labelled with its level', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  const rows = historyRows()
  expect(rows).toHaveLength(3)
  expect(rows[0].textContent).toContain("Added as 'Well'")
  expect(rows[0].textContent).toMatch(/first review graded Good/)
  expect(rows[1].textContent).toContain('Again')
  expect(rows[1].textContent).toContain('90%')
  expect(rows[2].textContent).toContain('81%')
  // Only the seed is a seed.
  expect(rows[1].textContent).not.toContain('Added as')
  expect(rows[2].textContent).not.toContain('Added as')
})

test('a seed has no predicted recall before it, shown as a dash rather than 0%', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  expect(historyRows()[0].textContent).toContain('Recall before-')
  expect(historyRows()[0].textContent).not.toContain('0%')
})

test('every statistic appears with its own explanation', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  const explanations = new Set<string>()
  for (const label of STATISTIC_LABELS) {
    const row = statistic(label)
    if (row === null) {
      throw new Error(`no ${label} statistic`)
    }
    const explanation = row.term.textContent?.slice(label.length).trim() ?? ''
    expect(explanation.length).toBeGreaterThan(10)
    explanations.add(explanation)
  }
  expect(explanations.size).toBe(STATISTIC_LABELS.length)
})

test('score and recall are two distinctly labelled percentages, as the backend sent them', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  expect(statistic('Score')?.value).toBe('23%')
  expect(statistic('Recall')?.value).toBe('96%')
  expect(statistic('Stability')?.value).toBe('3.4 days')
  expect(statistic('Difficulty')?.value).toBe('6.2 out of 10')
  expect(statistic('Reviews')?.value).toBe('2')
  expect(statistic('Lapses')?.value).toBe('1')
  expect(statistic('Added as')?.value).toBe('Well')
  expect(statistic('Next review')?.value).toContain('in 2 days')
})

test('the recall explanation says a fresh review, even a missed one, reads 100%', async () => {
  stubFetch(200, REVIEWED_WORD)

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  expect(statistic('Recall')?.term.textContent).toMatch(/100%.*missed/)
})

test('a due word says so beside its next review, from the backends flag', async () => {
  const statistics = { ...(REVIEWED_WORD.statistics as object), due: true }
  stubFetch(200, { ...REVIEWED_WORD, statistics })

  render(<WordDetailPage id={7} />)
  await screen.findByRole('heading', { name: '사과' })

  expect(statistic('Next review')?.value).toContain('due now')
})

test('a new word shows New for its score, and no recall and no next review', async () => {
  stubFetch(200, NEW_WORD)

  render(<WordDetailPage id={8} />)
  await screen.findByRole('heading', { name: '집' })

  expect(statistic('Score')?.value).toBe('New')
  expect(statistic('Recall')).toBeNull()
  expect(statistic('Next review')).toBeNull()
  // No figure reads 0%: a word with no memory has no percentage to show.
  const values = [...document.querySelectorAll('dd')].map((value) => value.textContent)
  expect(values).not.toContain('0%')
  expect(screen.getByText('No reviews yet.')).toBeDefined()
})

test('a word that does not exist says so and links to the list, with no alert', async () => {
  stubFetch(404, { detail: 'No word with id 99.' })

  render(<WordDetailPage id={99} />)

  expect(await screen.findByRole('heading', { name: /word not found/i })).toBeDefined()
  expect(screen.getByRole('link', { name: /back to the words/i }).getAttribute('href')).toBe('#/words')
  expect(screen.queryByRole('alert')).toBeNull()
})

test('any other failure shows an alert, not a blank page', async () => {
  stubFetch(500, { detail: 'The vocabulary database is newer than this app.' })

  render(<WordDetailPage id={7} />)

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe('The vocabulary database is newer than this app.')
  expect(screen.getByRole('link', { name: /all words/i }).getAttribute('href')).toBe('#/words')
})

test('a backend out of reach shows an alert too', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
  )

  render(<WordDetailPage id={7} />)

  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/could not reach the backend/i))
})

// Editing and deleting (vocab-words-ui T03).

interface Call {
  url: string
  method: string
  body: unknown
}

/** `GET` answers the reviewed word; `PUT` and `DELETE` answer `write`. */
function stubWrites(write: { status: number; body: unknown }): () => Call[] {
  const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET') {
      return Promise.resolve(jsonResponse(REVIEWED_WORD))
    }
    return Promise.resolve(jsonResponse(write.body, write.status))
  })
  vi.stubGlobal('fetch', fetchMock)
  return () =>
    fetchMock.mock.calls
      .map(([input, init]) => ({
        url: String(input),
        method: ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase(),
        body: (init as RequestInit | undefined)?.body
          ? JSON.parse(String((init as RequestInit).body))
          : undefined,
      }))
      .filter((call) => call.method !== 'GET')
}

async function openEdit(): Promise<void> {
  render(<WordDetailPage id={7} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
}

function editField(name: string | RegExp): HTMLInputElement {
  return screen.getByRole('textbox', { name }) as HTMLInputElement
}

test('editing starts from the word as typed: translations with semicolons, tags with commas', async () => {
  stubWrites({ status: 200, body: {} })
  await openEdit()

  expect(editField('Korean').value).toBe('사과')
  expect(editField('Translations').value).toBe('apple; pomme')
  expect(editField(/tags/i).value).toBe('food')
  expect(document.activeElement).toBe(editField('Korean'))
})

test('saving sends a PUT with the translations as typed, then shows the saved word', async () => {
  // A `PUT` answers the word without its history.
  const { history: _history, ...withoutHistory } = REVIEWED_WORD
  const saved = { ...withoutHistory, translations: ['apple', 'pomme', 'Apfel'], tags: ['food', 'fruit'] }
  const writes = stubWrites({ status: 200, body: saved })
  await openEdit()

  fireEvent.change(editField('Translations'), { target: { value: 'apple; pomme; Apfel' } })
  fireEvent.change(editField(/tags/i), { target: { value: 'food, fruit' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0]).toEqual({
    url: '/api/vocab/words/7',
    method: 'PUT',
    body: { korean: '사과', translations: 'apple; pomme; Apfel', tags: ['food', 'fruit'] },
  })
  expect(await screen.findByText('apple; pomme; Apfel')).toBeDefined()
  expect(screen.getByText('fruit')).toBeDefined()
  expect(screen.getByRole('status').textContent).toBe('Saved.')
  expect(screen.queryByRole('textbox', { name: 'Translations' })).toBeNull()
  // The page keeps the history it had.
  expect(historyRows()).toHaveLength(3)
})

test('a refused save shows the backends message and keeps the form open with what was typed', async () => {
  stubWrites({ status: 409, body: { detail: '학교 is already in your vocabulary.' } })
  await openEdit()

  fireEvent.change(editField('Korean'), { target: { value: '학교' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect((await screen.findByRole('alert')).textContent).toBe('학교 is already in your vocabulary.')
  expect(editField('Korean').value).toBe('학교')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDefined()
})

test('Enter while composing in the Korean field does not save; a plain Enter does', async () => {
  const writes = stubWrites({ status: 200, body: REVIEWED_WORD })
  await openEdit()

  fireEvent.keyDown(editField('Korean'), { key: 'Enter', isComposing: true })
  expect(writes()).toHaveLength(0)

  fireEvent.keyDown(editField('Korean'), { key: 'Enter' })
  await waitFor(() => expect(writes()).toHaveLength(1))
})

test('the Korean field of the edit form is set up for a Korean keyboard', async () => {
  stubWrites({ status: 200, body: {} })
  await openEdit()

  expect(editField('Korean').getAttribute('lang')).toBe('ko')
  expect(editField('Korean').getAttribute('autocapitalize')).toBe('off')
})

test('familiarity is shown in the edit form, and cannot be edited', async () => {
  stubWrites({ status: 200, body: {} })
  await openEdit()

  const form = screen.getByRole('heading', { name: 'Edit' }).parentElement as HTMLElement
  expect(form.textContent).toContain('Added as Well')
  expect(within(form).getAllByRole('textbox')).toHaveLength(3)
  expect(within(form).queryByRole('combobox')).toBeNull()
})

test('cancelling an edit sends nothing and puts the word back as it was', async () => {
  const writes = stubWrites({ status: 200, body: {} })
  await openEdit()

  fireEvent.change(editField('Korean'), { target: { value: '배' } })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(writes()).toHaveLength(0)
  expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('사과')
  expect(screen.queryByRole('textbox', { name: 'Korean' })).toBeNull()
})

test('the first click on delete only asks; confirming sends DELETE and opens the list', async () => {
  window.history.replaceState(null, '', '#/words/7')
  const writes = stubWrites({ status: 204, body: null })
  render(<WordDetailPage id={7} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Delete word' }))

  expect(writes()).toHaveLength(0)
  const question = screen.getByRole('group', { name: /delete this word/i })
  expect(question.textContent).toMatch(/history/)
  expect(document.activeElement).toBe(within(question).getByRole('button', { name: 'Keep it' }))

  fireEvent.click(within(question).getByRole('button', { name: 'Delete for good' }))

  await waitFor(() =>
    expect(writes()).toEqual([{ url: '/api/vocab/words/7', method: 'DELETE', body: undefined }]),
  )
  await waitFor(() => expect(window.location.hash).toBe('#/words'))
  window.history.replaceState(null, '', window.location.pathname)
})

test('keeping the word sends nothing', async () => {
  const writes = stubWrites({ status: 204, body: null })
  render(<WordDetailPage id={7} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Delete word' }))
  fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))

  expect(writes()).toHaveLength(0)
  expect(screen.queryByRole('group', { name: /delete this word/i })).toBeNull()
  expect(screen.getByRole('button', { name: 'Delete word' })).toBeDefined()
})

test('a failed delete says so and stays on the word', async () => {
  window.history.replaceState(null, '', '#/words/7')
  stubWrites({ status: 500, body: { detail: 'Internal Server Error' } })
  render(<WordDetailPage id={7} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Delete word' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect((await screen.findByRole('alert')).textContent).toBe('Internal Server Error')
  expect(window.location.hash).toBe('#/words/7')
  window.history.replaceState(null, '', window.location.pathname)
})
