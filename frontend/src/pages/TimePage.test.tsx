/**
 * The clock exercise page (time-exercise T05), against the ticket's test contract.
 *
 * Same conventions as `NumbersPage.test.tsx`: `cleanup()` explicit, no jest-dom, `fetch`
 * stubbed with canned responses shaped exactly like `api/routes/time_of_day.py`'s, and
 * `HTMLMediaElement.prototype.play` stubbed. The clock is driven through its keyboard
 * sliders and AM/PM buttons (T04), which sets any value without simulating geometry.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { jsonResponse } from '../testUtils'
import { TimePage } from './TimePage'

const LEVELS_PATH = '/api/exercises/time/levels'
const QUESTIONS_PATH = '/api/exercises/time/questions'
const ANSWER_PATH = /\/api\/exercises\/time\/questions\/[^/]+\/answer$/

const LEVELS = {
  levels: [
    { level: 'half_hour', minute_step: 30 },
    { level: 'five_minutes', minute_step: 5 },
    { level: 'any_minute', minute_step: 1 },
  ],
  default: 'five_minutes',
}

const SPOKEN = '오후 세 시 삼십오 분'

function questionStub(id: string, level = 'five_minutes', minuteStep = 5) {
  return {
    question_id: id,
    audio_url: `/api/exercises/time/questions/${id}/audio`,
    level,
    minute_step: minuteStep,
  }
}

function answerStub(verdict: 'correct' | 'incorrect') {
  return { verdict, expected: { period: 'pm', hour: 3, minute: 35 }, text: SPOKEN }
}

interface StubConfig {
  levelsRejects?: boolean
  questionsRejects?: boolean
  questionStatus?: number
  questionBody?: unknown
  answer?: unknown
  answerStatus?: number
}

let questionCount = 0

function stubFetch(config: StubConfig = {}): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith(LEVELS_PATH)) {
      return config.levelsRejects ? Promise.reject(new TypeError('Failed to fetch')) : Promise.resolve(jsonResponse(LEVELS))
    }
    if (url.endsWith(QUESTIONS_PATH)) {
      if (config.questionsRejects) {
        return Promise.reject(new TypeError('Failed to fetch'))
      }
      if (config.questionStatus !== undefined) {
        return Promise.resolve(jsonResponse(config.questionBody, config.questionStatus))
      }
      questionCount += 1
      const body = JSON.parse(String(init?.body)) as { level: string }
      const step = LEVELS.levels.find((entry) => entry.level === body.level)?.minute_step ?? 5
      return Promise.resolve(jsonResponse(questionStub(`t${questionCount}`, body.level, step)))
    }
    if (ANSWER_PATH.test(url)) {
      return Promise.resolve(jsonResponse(config.answer ?? answerStub('correct'), config.answerStatus ?? 200))
    }
    throw new Error(`Unhandled fetch in test: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function requestsTo(fetchMock: ReturnType<typeof vi.fn>, match: (url: string) => boolean): unknown[] {
  return fetchMock.mock.calls
    .filter((call) => match(String(call[0])))
    .map((call) => {
      const init = call[1] as RequestInit | undefined
      return init?.body === undefined ? undefined : (JSON.parse(String(init.body)) as unknown)
    })
}

const isCreate = (url: string) => url.endsWith(QUESTIONS_PATH)
const isAnswer = (url: string) => ANSWER_PATH.test(url)

let playSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  questionCount = 0
  playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  playSpy.mockRestore()
})

async function renderWithQuestion(config: StubConfig = {}) {
  const fetchMock = stubFetch(config)
  const view = render(<TimePage />)
  await waitFor(() => expect(view.container.querySelector('audio')).not.toBeNull())
  return { ...view, fetchMock }
}

function hourSlider(): HTMLElement {
  return screen.getByRole('slider', { name: /hour/i })
}

function minuteSlider(): HTMLElement {
  return screen.getByRole('slider', { name: /minute/i })
}

function press(element: HTMLElement, key: string, times = 1): void {
  for (let index = 0; index < times; index += 1) {
    fireEvent.keyDown(element, { key })
  }
}

/** Sets the clock to 3:35 PM from 12:00 AM with the keyboard and the toggle. */
function setThreeThirtyFivePm(): void {
  press(hourSlider(), 'ArrowUp', 3)
  press(minuteSlider(), 'ArrowUp', 7)
  fireEvent.click(screen.getByRole('button', { name: 'PM' }))
}

function levelSelect(): HTMLSelectElement {
  return screen.getByRole('combobox', { name: 'Minutes' }) as HTMLSelectElement
}

test('the level selector lists the catalogue with its default selected', async () => {
  await renderWithQuestion()
  const select = levelSelect()
  expect([...select.options].map((option) => option.value)).toEqual(['half_hour', 'five_minutes', 'any_minute'])
  expect(select.value).toBe('five_minutes')
})

test('on arrival, exactly one question is drawn at the default level and played', async () => {
  const { fetchMock, container } = await renderWithQuestion()
  expect(requestsTo(fetchMock, isCreate)).toEqual([{ level: 'five_minutes' }])
  expect(container.querySelector('audio')?.getAttribute('src')).toBe('/api/exercises/time/questions/t1/audio')
  await waitFor(() => expect(playSpy).toHaveBeenCalled())
})

test('choosing another level redraws at it and gives the clock its minute step', async () => {
  const { fetchMock, container } = await renderWithQuestion()
  fireEvent.change(levelSelect(), { target: { value: 'half_hour' } })
  await waitFor(() =>
    expect(container.querySelector('audio')?.getAttribute('src')).toBe('/api/exercises/time/questions/t2/audio'),
  )
  expect(requestsTo(fetchMock, isCreate)).toEqual([{ level: 'five_minutes' }, { level: 'half_hour' }])
  expect(container.innerHTML).not.toContain('/questions/t1/audio')
  press(minuteSlider(), 'ArrowUp')
  expect(minuteSlider().getAttribute('aria-valuenow')).toBe('30')
})

test('replay plays again without drawing again', async () => {
  const { fetchMock } = await renderWithQuestion()
  const plays = playSpy.mock.calls.length
  fireEvent.click(screen.getByRole('button', { name: 'Replay' }))
  expect(playSpy.mock.calls.length).toBe(plays + 1)
  expect(requestsTo(fetchMock, isCreate)).toHaveLength(1)
})

test('the clock starts at 12:00 AM', async () => {
  await renderWithQuestion()
  expect(hourSlider().getAttribute('aria-valuenow')).toBe('12')
  expect(minuteSlider().getAttribute('aria-valuenow')).toBe('0')
  expect(screen.getByRole('button', { name: 'AM' }).getAttribute('aria-pressed')).toBe('true')
})

test('submit sends exactly the clock position', async () => {
  const { fetchMock } = await renderWithQuestion()
  setThreeThirtyFivePm()
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
  await screen.findByRole('status')
  expect(requestsTo(fetchMock, isAnswer)).toEqual([{ period: 'pm', hour: 3, minute: 35 }])
})

test('a correct answer reads as correct', async () => {
  await renderWithQuestion({ answer: answerStub('correct') })
  setThreeThirtyFivePm()
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
  const feedback = await screen.findByRole('status')
  expect(feedback.textContent).toMatch(/^Correct!/)
  expect(feedback.getAttribute('data-tone')).toBe('success')
})

test('a wrong answer shows the expected time in digits and its Korean', async () => {
  await renderWithQuestion({ answer: answerStub('incorrect') })
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
  const feedback = await screen.findByRole('status')
  expect(feedback.textContent).toContain('Incorrect')
  expect(feedback.textContent).toContain('3:35 PM')
  expect(feedback.textContent).toContain(SPOKEN)
  expect(feedback.querySelector('[lang="ko"]')?.textContent).toBe(SPOKEN)
  expect(feedback.getAttribute('data-tone')).toBe('error')
})

test('the answer is nowhere in the page before a submission', async () => {
  const { container } = await renderWithQuestion()
  expect(container.innerHTML).not.toContain(SPOKEN)
  expect(container.innerHTML).not.toContain('3:35')
  expect(container.innerHTML).not.toMatch(/[가-힣]/)
})

test('Next is locked until a verdict, then draws again, clears the feedback and resets the clock', async () => {
  const { fetchMock, container } = await renderWithQuestion()
  const next = screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement
  expect(next.disabled).toBe(true)

  setThreeThirtyFivePm()
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
  await screen.findByRole('status')
  expect(next.disabled).toBe(false)
  expect((screen.getByRole('button', { name: 'Submit' }) as HTMLButtonElement).disabled).toBe(true)

  fireEvent.click(next)
  await waitFor(() =>
    expect(container.querySelector('audio')?.getAttribute('src')).toBe('/api/exercises/time/questions/t2/audio'),
  )
  expect(requestsTo(fetchMock, isCreate)).toHaveLength(2)
  expect(screen.queryByRole('status')).toBeNull()
  expect(hourSlider().getAttribute('aria-valuenow')).toBe('12')
  expect(minuteSlider().getAttribute('aria-valuenow')).toBe('0')
  expect(screen.getByRole('button', { name: 'AM' }).getAttribute('aria-pressed')).toBe('true')
})

test('a failed catalogue shows an alert', async () => {
  stubFetch({ levelsRejects: true })
  render(<TimePage />)
  expect((await screen.findByRole('alert')).textContent).toMatch(/backend/i)
})

test('a failed draw shows an alert', async () => {
  stubFetch({ questionsRejects: true })
  render(<TimePage />)
  expect((await screen.findByRole('alert')).textContent).toMatch(/backend/i)
})

test('a synthesis failure shows the backend detail verbatim', async () => {
  stubFetch({ questionStatus: 502, questionBody: { detail: 'Could not synthesise audio for this question.' } })
  render(<TimePage />)
  expect((await screen.findByRole('alert')).textContent).toBe('Could not synthesise audio for this question.')
})

test('a failed answer shows an alert and keeps the question', async () => {
  const { container } = await renderWithQuestion({ answer: { detail: 'No item.' }, answerStatus: 404 })
  fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
  expect((await screen.findByRole('alert')).textContent).toBe('No item.')
  expect(container.querySelector('audio')).not.toBeNull()
})
