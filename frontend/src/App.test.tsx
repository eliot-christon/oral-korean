/**
 * Tests for the app shell (vocab-words-ui T01 to T03): the page the URL fragment names, the
 * navigation, and the not-found page. What each page does is its own test file's business
 * (`pages/*.test.tsx`); here a page is only recognised by its heading.
 *
 * Same conventions as `pages/NumbersPage.test.tsx`: `cleanup()` is called explicitly, no
 * jest-dom matcher, `fetch` stubbed (every page loads its data on mount), and
 * `HTMLMediaElement.prototype.play` and `window.scrollTo` stubbed, since jsdom implements
 * neither.
 *
 * The starting hash is set with `history.replaceState`, which fires no `hashchange`, so a
 * test decides exactly when the shell hears about a change.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from './App'
import { jsonResponse, wordStub } from './testUtils'

const WORD_12 = wordStub({ id: 12, history: [] })
const NEW_LEVEL = {
  familiarity: 'new',
  grade: null,
  score: null,
  stability: null,
  first_review_in_days: null,
}

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/exercises/numbers/systems')) {
        return Promise.resolve(jsonResponse({ systems: [{ system: 'sino', minimum: 0, maximum: 100 }] }))
      }
      if (url.endsWith('/api/exercises/numbers/questions')) {
        return Promise.resolve(
          jsonResponse({ question_id: 'q1', audio_url: '/api/exercises/numbers/questions/q1/audio' }),
        )
      }
      if (url.endsWith('/api/vocab/tags')) {
        return Promise.resolve(jsonResponse({ tags: [] }))
      }
      if (url.endsWith('/api/vocab/words')) {
        return Promise.resolve(
          jsonResponse({ words: [], summary: { total: 0, new: 0, due: 0, average_score: null } }),
        )
      }
      if (url.endsWith('/api/vocab/familiarity')) {
        return Promise.resolve(jsonResponse({ levels: [NEW_LEVEL] }))
      }
      if (url.endsWith('/api/vocab/words/batch')) {
        return Promise.resolve(jsonResponse({ words: [wordStub(), wordStub({ id: 2 })] }, 201))
      }
      if (url.endsWith('/api/vocab/words/12')) {
        return Promise.resolve(jsonResponse(WORD_12))
      }
      throw new Error(`Unhandled fetch in test: ${url}`)
    }),
  )
}

function startAt(hash: string): void {
  window.history.replaceState(null, '', hash === '' ? window.location.pathname : hash)
}

function numbersHeading(): HTMLElement | null {
  return screen.queryByRole('heading', { name: 'Oral Korean' })
}

function notFoundHeading(): HTMLElement | null {
  return screen.queryByRole('heading', { name: /not found/i })
}

let scrollSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  stubFetch()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
  scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  startAt('')
})

test('with the hash empty, the numbers page renders', async () => {
  startAt('')

  render(<App />)

  expect(numbersHeading()).not.toBeNull()
  expect(await screen.findByRole('textbox', { name: /answer/i })).toBeDefined()
})

test('with an unknown hash, a not-found page links home and no numbers page renders', () => {
  startAt('#/nope')

  render(<App />)

  expect(notFoundHeading()).not.toBeNull()
  const home = screen.getByRole('link', { name: /back/i })
  expect(home.getAttribute('href')).toBe('#/')
  expect(numbersHeading()).toBeNull()
  expect(screen.queryByRole('textbox', { name: /answer/i })).toBeNull()
})

test('a hashchange swaps the page without a reload', async () => {
  startAt('#/numbers')
  render(<App />)
  expect(numbersHeading()).not.toBeNull()

  act(() => {
    startAt('#/nope')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })

  expect(notFoundHeading()).not.toBeNull()
  expect(numbersHeading()).toBeNull()

  act(() => {
    startAt('#/numbers')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })

  await waitFor(() => expect(numbersHeading()).not.toBeNull())
  expect(notFoundHeading()).toBeNull()
})

test.each(['', '#/', '#/numbers'])(
  'marks the numbers entry as the current page at %j, and nothing on the not-found page',
  (hash) => {
    startAt(hash)
    render(<App />)

    const navigation = screen.getByRole('navigation')
    const numbersLink = screen.getByRole('link', { name: 'Numbers' })
    expect(navigation.contains(numbersLink)).toBe(true)
    expect(numbersLink.getAttribute('aria-current')).toBe('page')
    cleanup()

    startAt('#/nope')
    render(<App />)
    expect(screen.getByRole('link', { name: 'Numbers' }).getAttribute('aria-current')).toBeNull()
  },
)

test('clicking the numbers entry from the not-found page opens the numbers page', async () => {
  startAt('#/nope')
  render(<App />)

  fireEvent.click(screen.getByRole('link', { name: 'Numbers' }))

  await waitFor(() => expect(window.location.hash).toBe('#/numbers'))
  await waitFor(() => expect(numbersHeading()).not.toBeNull())
  expect(notFoundHeading()).toBeNull()
})

function navigateTo(hash: string): void {
  act(() => {
    startAt(hash)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

test('the navigation lists the numbers exercise and the word list, in that order', () => {
  startAt('')
  render(<App />)

  const links = within(screen.getByRole('navigation')).getAllByRole('link')
  expect(links.map((link) => link.textContent)).toEqual(['Numbers', 'Words'])
  expect(links.map((link) => link.getAttribute('href'))).toEqual(['#/numbers', '#/words'])
})

test.each(['#/words', '#/words/12'])('marks Words as the current page at %j', async (hash) => {
  startAt(hash)
  render(<App />)

  const words = screen.getByRole('link', { name: 'Words' })
  expect(words.getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('link', { name: 'Numbers' }).getAttribute('aria-current')).toBeNull()
  // Let the page's own request settle inside the test.
  await screen.findByRole('heading', { level: 1 })
})

test('#/words renders the word list and #/words/12 that word', async () => {
  startAt('#/words')
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Words' })).toBeDefined()

  navigateTo('#/words/12')

  expect(await screen.findByRole('heading', { name: '사과' })).toBeDefined()
  expect(screen.queryByRole('heading', { name: 'Words' })).toBeNull()
})

test('a new page starts at the top, but the first one is left where the browser put it', async () => {
  startAt('#/words')
  render(<App />)
  await screen.findByRole('heading', { name: 'Words' })
  expect(scrollSpy).not.toHaveBeenCalled()

  navigateTo('#/words/12')

  expect(scrollSpy).toHaveBeenCalledWith(0, 0)
  await screen.findByRole('heading', { name: '사과' })
})

test('#/words/new renders the add page, under the Words entry', async () => {
  startAt('#/words/new')
  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Add words' })).toBeDefined()
  expect(screen.getByRole('link', { name: 'Words' }).getAttribute('aria-current')).toBe('page')
})

test('a pasted list lands on the word list, which says how many words were added', async () => {
  startAt('#/words/new')
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Paste a list' }))
  fireEvent.change(screen.getByRole('textbox', { name: /one per line/i }), {
    target: { value: '사과 ; apple\n집 ; house' },
  })

  fireEvent.click(screen.getByRole('button', { name: 'Add the list' }))

  expect(await screen.findByRole('heading', { name: 'Words' })).toBeDefined()
  expect(window.location.hash).toBe('#/words')
  expect((await screen.findByRole('status')).textContent).toBe('Added 2 words.')
})
