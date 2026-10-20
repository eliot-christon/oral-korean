/**
 * The calendar exercise page (date-exercise T04), against the ticket's test contract.
 *
 * Same conventions as `TimePage.test.tsx`: `cleanup()` explicit, no jest-dom, `fetch`
 * stubbed with canned responses shaped exactly like `api/routes/dates.py`'s, and
 * `HTMLMediaElement.prototype.play` stubbed. "Today" is pinned with `vi.setSystemTime` to
 * 21 September 2026 (only `Date` is mocked, so `waitFor` keeps its real timers).
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { jsonResponse } from '../testUtils'
import { DatePage } from './DatePage'

const RANGE_PATH = '/api/exercises/dates/year-range'
const QUESTIONS_PATH = '/api/exercises/dates/questions'
const ANSWER_PATH = /\/api\/exercises\/dates\/questions\/[^/]+\/answer$/
const WINDOW = { minimum: 1950, maximum: 2049 }
const HANGUL = /[가-힣]/

interface StubConfig {
  asksYear?: boolean
  rangeRejects?: boolean
  questionsRejects?: boolean
  answer?: unknown
  answerStatus?: number
}

let questionCount = 0

function answerStub(verdict: 'correct' | 'incorrect') {
  return { verdict, expected: { year: 2026, month: 6, day: 6 }, text: '이천이십육 년 유월 육 일' }
}

function stubFetch(config: StubConfig = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith(RANGE_PATH)) {
      return config.rangeRejects ? Promise.reject(new TypeError('Failed to fetch')) : Promise.resolve(jsonResponse(WINDOW))
    }
    if (url.endsWith(QUESTIONS_PATH)) {
      if (config.questionsRejects) {
        return Promise.reject(new TypeError('Failed to fetch'))
      }
      questionCount += 1
      const id = `d${questionCount}`
      return Promise.resolve(
        jsonResponse({
          question_id: id,
          audio_url: `/api/exercises/dates/questions/${id}/audio`,
          asks_year: config.asksYear ?? true,
        }),
      )
    }
    if (ANSWER_PATH.test(url)) {
      return Promise.resolve(jsonResponse(config.answer ?? answerStub('correct'), config.answerStatus ?? 200))
    }
    throw new Error(`Unhandled fetch in test: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function callsTo(fetchMock: ReturnType<typeof vi.fn>, match: (url: string) => boolean): unknown[] {
  return fetchMock.mock.calls
    .filter((call) => match(String(call[0])))
    .map((call) => {
      const init = call[1] as RequestInit | undefined
      return init?.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown)
    })
}

const isRange = (url: string) => url.endsWith(RANGE_PATH)
const isCreate = (url: string) => url.endsWith(QUESTIONS_PATH)
const isAnswer = (url: string) => ANSWER_PATH.test(url)

let playSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  questionCount = 0
  vi.setSystemTime(new Date(2026, 8, 21, 12))
  playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  playSpy.mockRestore()
})

async function renderWithQuestion(config: StubConfig = {}) {
  const fetchMock = stubFetch(config)
  const view = render(<DatePage />)
  await waitFor(() => expect(view.container.querySelector('audio')).not.toBeNull())
  return { ...view, fetchMock }
}

function heading(): string {
  return document.getElementById('calendar-heading')?.textContent ?? ''
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: 'Submit' })
}

function pickAndSubmit(dayName: string): void {
  fireEvent.click(screen.getByRole('button', { name: dayName }))
  fireEvent.click(submitButton())
}

test('on arrival, the year window and one question are fetched, and the audio plays', async () => {
  const { fetchMock, container } = await renderWithQuestion()

  expect(callsTo(fetchMock, isRange)).toHaveLength(1)
  expect(callsTo(fetchMock, isCreate)).toHaveLength(1)
  expect(container.querySelector('audio')?.getAttribute('src')).toBe('/api/exercises/dates/questions/d1/audio')
  await waitFor(() => expect(playSpy).toHaveBeenCalled())
})

test('a dated question shows the year control, bounded by the window, on the current month', async () => {
  await renderWithQuestion({ asksYear: true })
  const year = screen.getByRole<HTMLSelectElement>('combobox', { name: 'Year' })

  expect(year.options[0].value).toBe('1950')
  expect(year.options[year.options.length - 1].value).toBe('2049')
  expect(heading()).toBe('September 2026')
})

test('a dated question clamps the current year into the window', async () => {
  vi.setSystemTime(new Date(2070, 2, 3, 12))
  await renderWithQuestion({ asksYear: true })

  expect(heading()).toBe('March 2049')
})

test('a yearless question shows no year control and no year', async () => {
  await renderWithQuestion({ asksYear: false })

  expect(screen.queryByRole('combobox', { name: 'Year' })).toBeNull()
  expect(heading()).toBe('September')
})

test('Submit is disabled until a day is picked', async () => {
  await renderWithQuestion()
  expect(submitButton().disabled).toBe(true)

  fireEvent.click(screen.getByRole('button', { name: '21 September 2026' }))

  expect(submitButton().disabled).toBe(false)
})

test('a dated pick is sent with a 1-based month', async () => {
  const { fetchMock } = await renderWithQuestion({ asksYear: true })

  pickAndSubmit('21 September 2026')
  await screen.findByRole('status')

  expect(callsTo(fetchMock, isAnswer)).toEqual([{ year: 2026, month: 9, day: 21 }])
})

test('a yearless pick is sent with a null year', async () => {
  const { fetchMock } = await renderWithQuestion({ asksYear: false })
  for (let step = 0; step < 3; step += 1) {
    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }))
  }

  pickAndSubmit('6 June')
  await screen.findByRole('status')

  expect(callsTo(fetchMock, isAnswer)).toEqual([{ year: null, month: 6, day: 6 }])
})

test('a correct answer reads as correct', async () => {
  await renderWithQuestion({ answer: answerStub('correct') })

  pickAndSubmit('21 September 2026')
  const feedback = await screen.findByRole('status')

  expect(feedback.textContent).toMatch(/^Correct!/)
  expect(feedback.getAttribute('data-tone')).toBe('success')
})

test('a wrong answer shows the expected date in digits and its Korean', async () => {
  await renderWithQuestion({ answer: answerStub('incorrect') })

  pickAndSubmit('21 September 2026')
  const feedback = await screen.findByRole('status')

  expect(feedback.textContent).toContain('6 June 2026')
  expect(feedback.textContent).toContain('이천이십육 년 유월 육 일')
  expect(feedback.querySelector('[lang="ko"]')?.textContent).toBe('이천이십육 년 유월 육 일')
  expect(feedback.getAttribute('data-tone')).toBe('error')
})

test('a yearless expected date is shown without a year', async () => {
  await renderWithQuestion({
    asksYear: false,
    answer: { verdict: 'incorrect', expected: { year: null, month: 6, day: 6 }, text: '유월 육 일' },
  })

  pickAndSubmit('21 September')
  const feedback = await screen.findByRole('status')

  expect(feedback.textContent).toContain('It was 6 June (')
})

test('nothing of the answer is on the page before submitting: no Hangul at all', async () => {
  const { container } = await renderWithQuestion()

  expect(container.innerHTML).not.toMatch(HANGUL)
})

test('Next draws a new question and resets the pick, the feedback and the calendar', async () => {
  const { fetchMock, container } = await renderWithQuestion()
  fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
  pickAndSubmit('21 October 2026')
  await screen.findByRole('status')

  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() =>
    expect(container.querySelector('audio')?.getAttribute('src')).toBe('/api/exercises/dates/questions/d2/audio'),
  )

  expect(callsTo(fetchMock, isCreate)).toHaveLength(2)
  expect(screen.queryByRole('status')).toBeNull()
  expect(submitButton().disabled).toBe(true)
  expect(heading()).toBe('September 2026')
  expect(document.querySelector('[aria-pressed="true"][data-day]')).toBeNull()
})

test('Next is disabled on arrival and enabled after a verdict', async () => {
  await renderWithQuestion()
  const next = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Next' })
  expect(next().disabled).toBe(true)

  pickAndSubmit('21 September 2026')
  await screen.findByRole('status')

  expect(next().disabled).toBe(false)
})

test('replay plays again without drawing again', async () => {
  const { fetchMock } = await renderWithQuestion()
  const plays = playSpy.mock.calls.length

  fireEvent.click(screen.getByRole('button', { name: 'Replay' }))

  expect(playSpy.mock.calls.length).toBe(plays + 1)
  expect(callsTo(fetchMock, isCreate)).toHaveLength(1)
})

test('a failed year-range call shows an alert', async () => {
  stubFetch({ rangeRejects: true })
  render(<DatePage />)

  expect((await screen.findByRole('alert')).textContent).not.toBe('')
})

test('a failed create-question call shows an alert', async () => {
  stubFetch({ questionsRejects: true })
  render(<DatePage />)

  expect((await screen.findByRole('alert')).textContent).not.toBe('')
})

test("a refused answer shows the backend's detail verbatim", async () => {
  await renderWithQuestion({
    answer: { detail: 'This question does not ask for the year.' },
    answerStatus: 422,
  })

  pickAndSubmit('21 September 2026')

  expect((await screen.findByRole('alert')).textContent).toBe('This question does not ask for the year.')
})
