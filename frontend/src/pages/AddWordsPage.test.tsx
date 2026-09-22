/**
 * Tests for the add page (vocab-words-ui T03), against the ticket's test contract.
 *
 * `fetch` is stubbed with responses shaped like the vocabulary routes'
 * (`src/oral_korean/api/routes/vocab_words.py`): a word for `POST /api/vocab/words`, the added
 * words for `POST /api/vocab/words/batch`, `{"detail": {"errors": [...]}}` for a refused
 * paste, and the familiarity catalogue. Same conventions as `NumbersPage.test.tsx`: explicit
 * `cleanup()`, no jest-dom matcher.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { jsonResponse, wordStub } from '../testUtils'
import { AddWordsPage } from './AddWordsPage'

const WORDS_PATH = '/api/vocab/words'
const BATCH_PATH = '/api/vocab/words/batch'

/** The catalogue as the backend computes it; `firstReviewWell` lets a test change a figure. */
function catalogue(firstReviewWell = 2): unknown {
  return {
    levels: [
      { familiarity: 'new', grade: null, score: null, stability: null, first_review_in_days: null },
      { familiarity: 'a_little', grade: 'hard', score: 14, stability: 1.2931, first_review_in_days: 1 },
      { familiarity: 'well', grade: 'good', score: 20, stability: 2.3065, first_review_in_days: firstReviewWell },
      { familiarity: 'very_well', grade: 'easy', score: 38, stability: 8.2956, first_review_in_days: 8 },
    ],
  }
}

type Reply = { status: number; body: unknown } | 'network'

interface StubConfig {
  catalogue?: unknown
  /** What `POST /api/vocab/words` answers. */
  add?: Reply
  /** What `POST /api/vocab/words/batch` answers. */
  batch?: Reply
  /** Hold every add until the test calls the resolver it gets back. */
  holdAdds?: boolean
}

interface Recorded {
  url: string
  method: string
  body: unknown
}

function reply(answer: Reply): Promise<unknown> {
  return answer === 'network'
    ? Promise.reject(new TypeError('Failed to fetch'))
    : Promise.resolve(jsonResponse(answer.body, answer.status))
}

function stubFetch(config: StubConfig = {}): { requests: () => Recorded[]; release: () => void } {
  const held: (() => void)[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url === '/api/vocab/familiarity') {
      return Promise.resolve(jsonResponse(config.catalogue ?? catalogue()))
    }
    if (method === 'POST' && url === WORDS_PATH) {
      const answer = config.add ?? { status: 201, body: wordStub({ korean: '사과' }) }
      if (config.holdAdds) {
        return new Promise((resolve) => held.push(() => resolve(reply(answer))))
      }
      return reply(answer)
    }
    if (method === 'POST' && url === BATCH_PATH) {
      return reply(config.batch ?? { status: 201, body: { words: [wordStub(), wordStub({ id: 2 })] } })
    }
    throw new Error(`Unhandled fetch in test: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return {
    requests: () =>
      fetchMock.mock.calls
        .map(([input, init]) => ({
          url: String(input),
          method: ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase(),
          body: (init as RequestInit | undefined)?.body ? JSON.parse(String((init as RequestInit).body)) : undefined,
        }))
        .filter((request) => request.method !== 'GET'),
    release: () => held.splice(0).forEach((resolve) => resolve()),
  }
}

function field(name: string | RegExp): HTMLInputElement {
  return screen.getByRole('textbox', { name }) as HTMLInputElement
}

function familiaritySelect(): Promise<HTMLSelectElement> {
  return screen.findByRole('combobox', { name: /how well/i }) as Promise<HTMLSelectElement>
}

function addButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /^add/i }) as HTMLButtonElement
}

function type(name: string | RegExp, value: string): void {
  fireEvent.change(field(name), { target: { value } })
}

/** Fills the one-word form: 사과, `apple; pomme`, tags `food, fruit`, familiarity `well`. */
async function fillOneWord(): Promise<void> {
  fireEvent.change(await familiaritySelect(), { target: { value: 'well' } })
  type('Korean', '사과')
  type('Translations', 'apple; pomme')
  type(/tags/i, 'food, fruit')
}

async function choosePasteMode(): Promise<void> {
  fireEvent.click(await screen.findByRole('button', { name: 'Paste a list' }))
}

const PASTED = '사과 ; apple\n집 ; house; home'

beforeEach(() => {
  window.history.replaceState(null, '', '#/words/new')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

// One word.

test('one word sends the translations as typed, the tags as a list and the chosen familiarity', async () => {
  const { requests } = stubFetch()
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.click(addButton())

  await waitFor(() => expect(requests()).toHaveLength(1))
  expect(requests()[0]).toEqual({
    url: WORDS_PATH,
    method: 'POST',
    body: { korean: '사과', translations: 'apple; pomme', tags: ['food', 'fruit'], familiarity: 'well' },
  })
})

test('once added, Korean and translations clear, tags and familiarity stay, and focus is back on Korean', async () => {
  stubFetch()
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.click(addButton())

  const confirmation = await screen.findByRole('status')
  expect(confirmation.textContent).toContain('사과')
  expect(confirmation.querySelector('[lang="ko"]')?.textContent).toBe('사과')
  expect(field('Korean').value).toBe('')
  expect(field('Translations').value).toBe('')
  expect(field(/tags/i).value).toBe('food, fruit')
  expect((await familiaritySelect()).value).toBe('well')
  expect(document.activeElement).toBe(field('Korean'))
})

test('a duplicate shows the backends message and keeps every field', async () => {
  stubFetch({ add: { status: 409, body: { detail: '사과 is already in your vocabulary.' } } })
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.click(addButton())

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe('사과 is already in your vocabulary.')
  expect(field('Korean').value).toBe('사과')
  expect(field('Translations').value).toBe('apple; pomme')
  expect(field(/tags/i).value).toBe('food, fruit')
  expect((await familiaritySelect()).value).toBe('well')
  expect(screen.queryByRole('status')).toBeNull()
})

test('an invalid word shows the backends message', async () => {
  stubFetch({ add: { status: 422, body: { detail: 'The Korean side has no Hangul: write the word in Korean script.' } } })
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.click(addButton())

  expect((await screen.findByRole('alert')).textContent).toBe(
    'The Korean side has no Hangul: write the word in Korean script.',
  )
  expect(field('Korean').value).toBe('사과')
})

test('Enter while an input method is composing does not submit; a plain Enter does', async () => {
  const { requests } = stubFetch()
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.keyDown(field('Korean'), { key: 'Enter', isComposing: true })
  // Safari reports a composing key press as key code 229 instead.
  fireEvent.keyDown(field('Korean'), { key: 'Enter', keyCode: 229 })
  expect(requests()).toHaveLength(0)

  fireEvent.keyDown(field('Korean'), { key: 'Enter', isComposing: false })

  await waitFor(() => expect(requests()).toHaveLength(1))
  expect(requests()[0].body).toEqual(expect.objectContaining({ korean: '사과' }))
})

test('submitting is disabled while Korean or translations is blank', async () => {
  const { requests } = stubFetch()
  render(<AddWordsPage />)
  await familiaritySelect()
  expect(addButton().disabled).toBe(true)

  type('Korean', '사과')
  expect(addButton().disabled).toBe(true)
  type('Translations', '   ')
  expect(addButton().disabled).toBe(true)
  fireEvent.keyDown(field('Korean'), { key: 'Enter' })

  type('Translations', 'apple')
  expect(addButton().disabled).toBe(false)
  expect(requests()).toHaveLength(0)
})

test('clicking twice quickly sends one request, and the button waits for the answer', async () => {
  const { requests, release } = stubFetch({ holdAdds: true })
  render(<AddWordsPage />)
  await fillOneWord()

  fireEvent.click(addButton())
  fireEvent.click(addButton())
  fireEvent.keyDown(field('Korean'), { key: 'Enter' })

  await waitFor(() => expect(requests()).toHaveLength(1))
  expect(addButton().disabled).toBe(true)

  await act(async () => {
    release()
  })
  await screen.findByRole('status')
  expect(requests()).toHaveLength(1)
})

test('the Korean field is set up for a Korean keyboard', async () => {
  stubFetch()
  render(<AddWordsPage />)
  await familiaritySelect()

  const korean = field('Korean')
  expect(korean.getAttribute('lang')).toBe('ko')
  expect(korean.getAttribute('autocapitalize')).toBe('off')
  expect(korean.getAttribute('autocorrect')).toBe('off')
  expect(korean.getAttribute('spellcheck')).toBe('false')
  expect(korean.getAttribute('autocomplete')).toBe('off')
})

test('the familiarity options are the catalogues four levels in its order, new preselected', async () => {
  stubFetch()
  render(<AddWordsPage />)

  const select = await familiaritySelect()
  const options = within(select).getAllByRole('option') as HTMLOptionElement[]
  expect(options.map((option) => option.value)).toEqual(['new', 'a_little', 'well', 'very_well'])
  expect(select.value).toBe('new')
  expect(options[2].textContent).toContain('2 days')
  expect(options[3].textContent).toContain('8 days')
})

test('an options delay is the catalogues figure: change the figure and the text follows', async () => {
  stubFetch({ catalogue: catalogue(5) })
  render(<AddWordsPage />)

  const select = await familiaritySelect()
  const well = within(select).getByRole('option', { name: /^well/i })
  expect(well.textContent).toContain('5 days')
  expect(well.textContent).not.toContain('2 days')
})

// Paste a list.

test('a pasted list is sent whole, line breaks included, with the batchs tags and familiarity', async () => {
  const { requests } = stubFetch()
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(await familiaritySelect(), { target: { value: 'a_little' } })
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })
  type(/tags/i, 'topik 1')

  fireEvent.click(addButton())

  await waitFor(() => expect(requests()).toHaveLength(1))
  expect(requests()[0]).toEqual({
    url: BATCH_PATH,
    method: 'POST',
    body: { text: PASTED, tags: ['topik 1'], familiarity: 'a_little' },
  })
})

test('an added list opens the word list', async () => {
  stubFetch()
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })

  fireEvent.click(addButton())

  // The confirmation is left for the list, which shows it: see App.test.tsx.
  await waitFor(() => expect(window.location.hash).toBe('#/words'))
})

test('a refused list lists every error with its line number and keeps the text', async () => {
  stubFetch({
    batch: {
      status: 422,
      body: {
        detail: {
          errors: [
            { line: 2, message: 'The Korean side has no Hangul: write the word in Korean script.' },
            { line: 5, message: 'No ";" or tab between the Korean and its translations.' },
          ],
        },
      },
    },
  })
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })

  fireEvent.click(addButton())

  const alert = await screen.findByRole('alert')
  const lines = within(alert).getAllByRole('listitem').map((item) => item.textContent)
  expect(lines).toEqual([
    'Line 2: The Korean side has no Hangul: write the word in Korean script.',
    'Line 5: No ";" or tab between the Korean and its translations.',
  ])
  expect(field(/one per line/i).value).toBe(PASTED)
  expect(window.location.hash).toBe('#/words/new')
})

test('a problem no line owns is listed without a line number', async () => {
  stubFetch({
    batch: { status: 422, body: { detail: { errors: [{ line: null, message: '사과 is already in your vocabulary.' }] } } },
  })
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })

  fireEvent.click(addButton())

  const alert = await screen.findByRole('alert')
  expect(within(alert).getByRole('listitem').textContent).toBe('사과 is already in your vocabulary.')
})

test.each<[string, Reply]>([
  ['the network failing', 'network'],
  ['a server error', { status: 500, body: { detail: 'Internal Server Error' } }],
])('%s shows an alert and keeps the text', async (_case, answer) => {
  stubFetch({ batch: answer })
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })

  fireEvent.click(addButton())

  expect((await screen.findByRole('alert')).textContent).toBeTruthy()
  expect(field(/one per line/i).value).toBe(PASTED)
  expect(window.location.hash).toBe('#/words/new')
})

test('in the paste list, Enter is a line break, never a submission', async () => {
  const { requests } = stubFetch()
  render(<AddWordsPage />)
  await choosePasteMode()
  fireEvent.change(field(/one per line/i), { target: { value: PASTED } })

  fireEvent.keyDown(field(/one per line/i), { key: 'Enter' })

  expect(requests()).toHaveLength(0)
})

test('the mode buttons say which mode is on', async () => {
  stubFetch()
  render(<AddWordsPage />)

  const one = await screen.findByRole('button', { name: 'One word' })
  const paste = screen.getByRole('button', { name: 'Paste a list' })
  expect(one.getAttribute('aria-pressed')).toBe('true')
  expect(paste.getAttribute('aria-pressed')).toBe('false')

  fireEvent.click(paste)

  expect(one.getAttribute('aria-pressed')).toBe('false')
  expect(paste.getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('textbox', { name: 'Korean' })).toBeNull()
})
