/**
 * Tests for choosing a session's words on the start form (vocab-directions T04): the learn
 * queue editor and the review picker, rendered through `SessionPage` so the start request is
 * the real one.
 *
 * `fetch` is stubbed with canned responses shaped like T03's routes in
 * `src/oral_korean/api/routes/vocab_sessions.py`. Same conventions as `SessionPage.test.tsx`:
 * explicit `cleanup()`, no jest-dom matcher.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { jsonResponse } from '../testUtils'
import { SessionPage } from './SessionPage'

const A = { id: 1, korean: '사과', translations: ['apple'], tags: [] }
const B = { id: 2, korean: '배', translations: ['pear'], tags: [] }
const C = { id: 3, korean: '감', translations: ['persimmon'], tags: [] }

const DUE_1 = { ...A, due: true, next_review: '2026-09-25T10:00:00Z' }
const DUE_2 = { ...B, due: true, next_review: '2026-09-26T10:00:00Z' }
const LATER = { ...C, due: false, next_review: '2026-10-02T10:00:00Z' }

type Reply = { status: number; body: unknown }

interface Stub {
  queue?: unknown[]
  reorder?: Reply
  candidates?: unknown[]
}

function stubFetch(stub: Stub): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    let reply: Reply | undefined
    if (url === '/api/vocab/tags') {
      reply = { status: 200, body: { tags: [] } }
    } else if (url.startsWith('/api/vocab/words')) {
      reply = { status: 200, body: { words: [], summary: { total: 3, new: 3, due: 2, average_score: null } } }
    } else if (url.startsWith('/api/vocab/learn-queue') && init?.method === 'PUT') {
      reply = stub.reorder
    } else if (url.startsWith('/api/vocab/learn-queue')) {
      reply = { status: 200, body: { words: stub.queue ?? [] } }
    } else if (url.startsWith('/api/vocab/review-candidates')) {
      reply = { status: 200, body: { words: stub.candidates ?? [] } }
    } else if (url === '/api/vocab/sessions') {
      reply = { status: 201, body: { session_id: 's1', kind: 'review', word_count: 3, directions: [] } }
    } else if (url === '/api/vocab/sessions/s1/next') {
      reply = { status: 200, body: { type: 'end', summary: { words: [], word_count: 0, correct_count: 0 } } }
    }
    if (reply === undefined) {
      throw new Error(`Unhandled fetch in test: ${url}`)
    }
    return jsonResponse(reply.body, reply.status)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodiesSent(fetchMock: ReturnType<typeof vi.fn>, url: string, method: string): unknown[] {
  return fetchMock.mock.calls
    .filter((call) => String(call[0]) === url && (call[1] as RequestInit | undefined)?.method === method)
    .map((call) => JSON.parse(String((call[1] as RequestInit).body)) as unknown)
}

function button(name: string): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement
}

function checkbox(name: RegExp): HTMLInputElement {
  return screen.getByRole('checkbox', { name }) as HTMLInputElement
}

/** The Korean of each word of a list, top first. */
function koreanIn(list: HTMLElement): string[] {
  return within(list)
    .getAllByRole('listitem')
    .map((item) => item.querySelector('[lang="ko"]')?.textContent ?? '')
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------------
// The learn queue
// ---------------------------------------------------------------------------------

test('the first words of the queue, as many as the session takes, are marked as next', async () => {
  stubFetch({ queue: [A, B, C] })
  render(<SessionPage kind="learn" />)

  const list = await screen.findByRole('list', { name: 'Learn queue' })
  fireEvent.change(screen.getByLabelText(/Number of words/), { target: { value: '2' } })

  expect(koreanIn(list)).toEqual(['사과', '배', '감'])
  const marked = within(list)
    .getAllByRole('listitem')
    .map((item) => within(item).queryByText('Next session') !== null)
  expect(marked).toEqual([true, true, false])
})

test('moving a word to the top saves it and shows the order the backend answers with', async () => {
  const fetchMock = stubFetch({ queue: [A, B, C], reorder: { status: 200, body: { words: [C, A, B] } } })
  render(<SessionPage kind="learn" />)
  const list = await screen.findByRole('list', { name: 'Learn queue' })

  fireEvent.click(button('Move 감 to top'))

  await waitFor(() => expect(koreanIn(list)).toEqual(['감', '사과', '배']))
  expect(bodiesSent(fetchMock, '/api/vocab/learn-queue', 'PUT')).toEqual([{ word_ids: [3] }])
})

test('moving a word down sends the whole list shown, in its new order', async () => {
  const fetchMock = stubFetch({ queue: [A, B, C], reorder: { status: 200, body: { words: [B, A, C] } } })
  render(<SessionPage kind="learn" />)
  const list = await screen.findByRole('list', { name: 'Learn queue' })

  fireEvent.click(button('Move 사과 down'))

  await waitFor(() => expect(koreanIn(list)).toEqual(['배', '사과', '감']))
  expect(bodiesSent(fetchMock, '/api/vocab/learn-queue', 'PUT')).toEqual([{ word_ids: [2, 1, 3] }])
})

test('the first word cannot move up and the last cannot move down', async () => {
  stubFetch({ queue: [A, B, C] })
  render(<SessionPage kind="learn" />)
  await screen.findByRole('list', { name: 'Learn queue' })

  expect(button('Move 사과 up').disabled).toBe(true)
  expect(button('Move 사과 to top').disabled).toBe(true)
  expect(button('Move 감 down').disabled).toBe(true)
  expect(button('Move 배 up').disabled).toBe(false)
  expect(button('Move 배 down').disabled).toBe(false)
})

test('a refused move shows an alert and leaves the order as it was', async () => {
  stubFetch({ queue: [A, B, C], reorder: { status: 422, body: { detail: 'No word with id 3.' } } })
  render(<SessionPage kind="learn" />)
  const list = await screen.findByRole('list', { name: 'Learn queue' })

  fireEvent.click(button('Move 감 to top'))

  expect((await screen.findByRole('alert')).textContent).toContain('No word with id 3.')
  expect(koreanIn(list)).toEqual(['사과', '배', '감'])
})

// ---------------------------------------------------------------------------------
// The review picker
// ---------------------------------------------------------------------------------

test('the due words are selected and the others are not', async () => {
  stubFetch({ candidates: [DUE_1, DUE_2, LATER] })
  render(<SessionPage kind="review" />)
  await screen.findByRole('list', { name: 'Words to review' })

  expect(checkbox(/사과/).checked).toBe(true)
  expect(checkbox(/배/).checked).toBe(true)
  expect(checkbox(/감/).checked).toBe(false)
  expect(within(screen.getByRole('list', { name: 'Words not selected' })).getByText('Not due yet')).toBeDefined()
})

test('a word chosen early and moved to the top leads the review', async () => {
  const fetchMock = stubFetch({ candidates: [DUE_1, DUE_2, LATER] })
  render(<SessionPage kind="review" />)
  await screen.findByRole('list', { name: 'Words to review' })

  fireEvent.click(checkbox(/감/))
  fireEvent.click(button('Move 감 to top'))
  fireEvent.click(button('Start'))

  await waitFor(() => expect(bodiesSent(fetchMock, '/api/vocab/sessions', 'POST')).toHaveLength(1))
  expect(bodiesSent(fetchMock, '/api/vocab/sessions', 'POST')[0]).toMatchObject({
    kind: 'review',
    word_ids: [3, 1, 2],
  })
  expect(fetchMock.mock.calls.some((call) => String(call[0]).startsWith('/api/vocab/learn-queue'))).toBe(false)
})

test('with nothing selected, Start is disabled', async () => {
  stubFetch({ candidates: [DUE_1, LATER] })
  render(<SessionPage kind="review" />)
  await screen.findByRole('list', { name: 'Words to review' })
  expect(button('Start').disabled).toBe(false)

  fireEvent.click(checkbox(/사과/))

  expect(button('Start').disabled).toBe(true)
})

test('every Korean word on the start form is marked as Korean', async () => {
  stubFetch({ candidates: [DUE_1, DUE_2, LATER] })
  const { container } = render(<SessionPage kind="review" />)
  await screen.findByRole('list', { name: 'Words to review' })

  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const hangul: Text[] = []
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    if (/[가-힣]/.test(node.textContent ?? '')) {
      hangul.push(node as Text)
    }
  }
  expect(hangul.length).toBe(3)
  expect(hangul.every((node) => node.parentElement?.closest('[lang="ko"]') !== null)).toBe(true)
})
