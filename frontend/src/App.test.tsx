/**
 * Tests for the number-recognition exercise page (T05), against the ticket's own
 * "Test contract" (`.claude/work/numbers-exercise/tickets/T05-frontend-number-entry.md`).
 *
 * Write-mode note: `App.tsx` and `api.ts` now implement the real page (T05 is done); every
 * test below runs against that implementation, not a stub. `fetch` is stubbed per-test with
 * canned JSON responses shaped exactly like T04's real routes (`tests/test_api_numbers.py`
 * pins the Python side of the same contract); `HTMLMediaElement.prototype.play` is stubbed
 * globally since jsdom does not implement it. No network, no real audio, ever.
 *
 * Added once the implementation existed (framing mode could not have anticipated these):
 *   - the `maximumOverride` vs. catalogue-default interaction - typing a custom maximum is
 *     sent on the next draw for the *same* system, but is dropped in favour of the new
 *     system's own catalogue maximum when the system selector changes.
 *   - the range control's `min`, not just `max`, tracks the selected system (native Korean
 *     starts at 1, sino-Korean at 0 - a real difference, not an arbitrary extra assertion).
 *   - the `<audio>` element and the replay button are only usable once a question has
 *     actually arrived (conditional mount), not merely once the catalogue has loaded.
 *   - a failed *answer* submission (as opposed to a failed create-question, which framing
 *     already covered) shows an error without discarding the still-valid current question.
 *
 * This file treats `App.tsx` as the whole page (no `components/` split), per the plan
 * described in the ticket hand-off: nothing here needed a component boundary to be
 * testable, so none was assumed.
 *
 * `@testing-library/jest-dom` is not a dependency of this project (see `package.json`),
 * so every assertion below reads plain DOM properties (`.value`, `.textContent`,
 * `.getAttribute(...)`) through vitest's own `expect`, matching the existing smoke test's
 * style - not `toBeInTheDocument()`/`toHaveValue()`-style custom matchers.
 *
 * `@testing-library/react`'s automatic `afterEach(cleanup)` only registers itself when it
 * finds a *global* `afterEach` (see its `dist/index.js`); this project never sets
 * `test.globals: true` in `vite.config.ts` (T01's choice, kept as-is - "no new frontend
 * tooling"), and every test file here imports `afterEach` from `vitest` explicitly rather
 * than relying on a global. So auto-cleanup would silently never run, and repeated
 * `render(<App />)` calls across this file's many tests would stack up in `document.body`.
 * `cleanup()` is therefore called explicitly below, rather than assumed.
 *
 * Judgment calls this file makes (the ticket does not name markup, so these are design
 * constraints on `App.tsx` the implementation must satisfy for these tests to pass):
 *   - the numeral-system choice is a single `<select>` (native `combobox` role, no
 *     `multiple`/`size`), with an accessible name matching /system/i, and its two
 *     `<option>`s are named "Sino-Korean" and "Native Korean" (case-insensitive).
 *   - the range control is a single `<input type="number">` (`spinbutton` role) with an
 *     accessible name matching /maximum/i, whose `min`/`max` attributes are set from the
 *     selected system's catalogue entry.
 *   - the answer field is `<input type="text">` (`textbox` role, *not* `type="number"`)
 *     with an accessible name matching /answer/i. This is load-bearing, not cosmetic: a
 *     real `type="number"` input sanitises an invalid value back to `""` before React ever
 *     sees it (the HTML "value sanitisation algorithm"), which would make the non-numeric
 *     answer impossible to type at all - so the ticket's "not a number" acceptance
 *     criterion is only reachable if this field accepts arbitrary text.
 *   - submit/replay/next are `<button>`s (`button` role) named /submit/i, /replay/i,
 *     /next/i respectively, and the reveal control is a fourth one named /show answer/i
 *     (`numbers-answer-before-next`). Next is locked while a question is in hand without a
 *     verdict, and unlocked by a verdict from either Submit or Show answer; Show answer
 *     is a Submit of an empty answer, so it goes through the same answer endpoint.
 *   - the question's `<audio>` element is a plain `<audio>` tag, queried via
 *     `container.querySelector('audio')` since neither `@testing-library/dom` nor jsdom
 *     gives it a distinguishing ARIA role.
 *   - answer feedback (correct/incorrect/not-a-number) renders inside one element with
 *     `role="status"`, whose text literally contains the word "correct" (correct),
 *     "incorrect" (wrong - checked with a `\b` word boundary so it does not also satisfy
 *     the "correct" check, since "incorrect" contains "correct" as a substring) or a
 *     phrase matching /not.*number/i (not-a-number).
 *   - a failed create-question request renders one element with `role="alert"`.
 * Any of these is a reasonable default, not the only valid one; if the real `App.tsx`
 * picks a different shape, whoever writes it should either match these or say why not.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from './App'
import { classTokensIn } from './testUtils'

const SYSTEMS_PATH = '/api/exercises/numbers/systems'
const QUESTIONS_PATH = '/api/exercises/numbers/questions'
const ANSWER_PATH_PATTERN = /\/questions\/[^/]+\/answer$/

// Matches `korean/numerals.py`'s `_SUPPORTED_RANGES` (see `tests/test_numerals.py`):
// Sino-Korean 0-100, native Korean 1-99. Real numbers rather than arbitrary ones, so a
// test that reads them back off the stubbed catalogue instead of hardcoding "99" still
// means something.
const SINO_SYSTEM_INFO = { system: 'sino', minimum: 0, maximum: 100 }
const NATIVE_SYSTEM_INFO = { system: 'native', minimum: 1, maximum: 99 }
const DEFAULT_SYSTEMS_RESPONSE = { systems: [SINO_SYSTEM_INFO, NATIVE_SYSTEM_INFO] }

/**
 * A create-question stub carrying *only* `question_id` and `audio_url` - deliberately
 * never `system`, `number` or `text`, even though the real T04 response also carries
 * `system`. Used by every test in this file, so no test here can accidentally depend on
 * a field arriving before the answer is submitted (the ticket's own "the answer never
 * arrives early" contract line).
 */
function questionStub(id: string): { question_id: string; audio_url: string } {
  return { question_id: id, audio_url: `/api/exercises/numbers/questions/${id}/audio` }
}

function jsonResponse(
  body: unknown,
  status = 200,
): { ok: boolean; status: number; json: () => Promise<unknown> } {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) }
}

interface FetchStubConfig {
  /** Body of the `GET .../systems` response. Defaults to both systems, sino first. */
  systems?: unknown
  /** When true, the `GET .../systems` call rejects instead of resolving. */
  systemsRejects?: boolean
  /**
   * One entry consumed per `POST .../questions` call, in order; the last entry repeats
   * once exhausted, so a test that does not care how many times a question is drawn
   * does not need to pad this array out.
   */
  questions?: unknown[]
  /** When true, every `POST .../questions` call rejects instead of resolving. */
  questionsRejects?: boolean
  /** Body of every `POST .../answer` response. */
  answer?: unknown
  /** When true, every `POST .../answer` call rejects instead of resolving. */
  answerRejects?: boolean
}

/** A recorded call to the stubbed `fetch`, with a JSON body parsed for convenience. */
interface RecordedRequest {
  url: string
  method: string
  body: unknown
}

function recordedRequests(fetchMock: ReturnType<typeof vi.fn>): RecordedRequest[] {
  return fetchMock.mock.calls.map((call) => {
    const input = call[0] as RequestInfo | URL
    const init = call[1] as RequestInit | undefined
    return {
      url: String(input),
      method: (init?.method ?? 'GET').toUpperCase(),
      body: init?.body != null ? JSON.parse(String(init.body)) : undefined,
    }
  })
}

function questionCreationRequests(fetchMock: ReturnType<typeof vi.fn>): RecordedRequest[] {
  return recordedRequests(fetchMock).filter(
    (request) => request.method === 'POST' && request.url.endsWith(QUESTIONS_PATH),
  )
}

function answerRequests(fetchMock: ReturnType<typeof vi.fn>): RecordedRequest[] {
  return recordedRequests(fetchMock).filter(
    (request) => request.method === 'POST' && ANSWER_PATH_PATTERN.test(request.url),
  )
}

/** Stubs `fetch` with canned responses for the three endpoints `App` is expected to call. */
function stubFetch(config: FetchStubConfig = {}): ReturnType<typeof vi.fn> {
  const remainingQuestions = [...(config.questions ?? [questionStub('q1')])]

  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()

    if (method === 'GET' && url.endsWith(SYSTEMS_PATH)) {
      if (config.systemsRejects) {
        return Promise.reject(new Error('network down'))
      }
      return Promise.resolve(jsonResponse(config.systems ?? DEFAULT_SYSTEMS_RESPONSE))
    }

    if (method === 'POST' && url.endsWith(QUESTIONS_PATH)) {
      if (config.questionsRejects) {
        return Promise.reject(new Error('network down'))
      }
      const next = remainingQuestions.length > 1 ? remainingQuestions.shift() : remainingQuestions[0]
      return Promise.resolve(jsonResponse(next))
    }

    if (method === 'POST' && ANSWER_PATH_PATTERN.test(url)) {
      if (config.answerRejects) {
        return Promise.reject(new Error('network down'))
      }
      return Promise.resolve(
        jsonResponse(config.answer ?? { verdict: 'correct', expected_number: 1, text: '일' }),
      )
    }

    throw new Error(`Unhandled fetch in test: ${method} ${url}`)
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Types `value` into the answer field and clicks submit. */
async function answerQuestion(value: string): Promise<void> {
  const answerInput = (await screen.findByRole('textbox', { name: /answer/i })) as HTMLInputElement
  fireEvent.change(answerInput, { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: /submit/i }))
}

/** Resolves once a question has actually arrived, i.e. once its `<audio>` is mounted. */
async function waitForQuestion(container: HTMLElement): Promise<void> {
  await waitFor(() => expect(container.querySelector('audio')).not.toBeNull())
}

function nextButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /next/i }) as HTMLButtonElement
}

function showAnswerButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /show answer|reveal/i }) as HTMLButtonElement
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement
}

let playSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  // jsdom does not implement HTMLMediaElement.prototype.play; every test renders an
  // <audio> element that App is expected to call .play() on.
  playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  playSpy.mockRestore()
})

test('renders the application heading once the backend catalogue and a first question have loaded', async () => {
  const fetchMock = stubFetch()

  render(<App />)

  const heading = screen.getByRole('heading', { name: 'Oral Korean' })
  expect(heading.textContent).toBe('Oral Korean')
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
})

test('builds the system selector from the backends catalogue, with Sino-Korean preselected', async () => {
  stubFetch()

  render(<App />)

  const selector = (await screen.findByRole('combobox', { name: /system/i })) as HTMLSelectElement
  expect(within(selector).getByRole('option', { name: /sino-korean/i })).toBeDefined()
  expect(within(selector).getByRole('option', { name: /native korean/i })).toBeDefined()
  expect(selector.value).toBe('sino')
})

test('draws a question on load and sets the audio elements source from the response', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1')] })

  const { container } = render(<App />)

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q1/audio',
    )
  })
})

test('choosing native Korean redraws with a native payload and drops the previous audio url', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1'), questionStub('q2')] })

  const { container } = render(<App />)

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q1/audio',
    )
  })

  const selector = (await screen.findByRole('combobox', { name: /system/i })) as HTMLSelectElement
  fireEvent.change(selector, { target: { value: 'native' } })

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(questionCreationRequests(fetchMock)[1].body).toEqual(
    expect.objectContaining({ system: 'native' }),
  )

  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q2/audio',
    )
  })
  expect(container.innerHTML).not.toContain('/questions/q1/audio')
})

test('bounds the range control by the selected systems catalogue minimum and maximum', async () => {
  stubFetch({ questions: [questionStub('q1'), questionStub('q2')] })

  render(<App />)

  const selector = (await screen.findByRole('combobox', { name: /system/i })) as HTMLSelectElement
  const initialRangeInput = (await screen.findByRole('spinbutton', {
    name: /maximum/i,
  })) as HTMLInputElement
  expect(initialRangeInput.min).toBe(String(SINO_SYSTEM_INFO.minimum))
  expect(initialRangeInput.max).toBe(String(SINO_SYSTEM_INFO.maximum))

  fireEvent.change(selector, { target: { value: 'native' } })

  // Re-queried rather than reusing `initialRangeInput`, in case the implementation
  // remounts the range control instead of updating it in place on a system switch.
  // Native Korean's minimum (1) differs from sino-Korean's (0), so this is a real bound,
  // not an arbitrary extra assertion.
  await waitFor(() => {
    const rangeInput = screen.getByRole('spinbutton', { name: /maximum/i }) as HTMLInputElement
    expect(rangeInput.min).toBe(String(NATIVE_SYSTEM_INFO.minimum))
    expect(rangeInput.max).toBe(String(NATIVE_SYSTEM_INFO.maximum))
  })
})

test('a custom maximum typed into the range control is sent on the next draw for the same system', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1'), questionStub('q2')] })

  const { container } = render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const maxInput = (await screen.findByRole('spinbutton', { name: /maximum/i })) as HTMLInputElement
  fireEvent.change(maxInput, { target: { value: '10' } })
  expect(maxInput.value).toBe('10')

  // Next is locked until the question has a verdict, so q1 is answered before moving on.
  await waitForQuestion(container)
  await answerQuestion('1')
  await screen.findByRole('status')

  fireEvent.click(screen.getByRole('button', { name: /next/i }))

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(questionCreationRequests(fetchMock)[1].body).toEqual(
    expect.objectContaining({ system: 'sino', maximum: 10 }),
  )
})

test('a maximum typed beyond the selected systems bounds is clamped, not sent as-is', async () => {
  // A value above the catalogue maximum must not be constructible from this control at
  // all - relying on the backend's own 422 to catch it would still let native Korean
  // (1-99) be asked for up to whatever the user typed, one request too late.
  const fetchMock = stubFetch({ questions: [questionStub('q1'), questionStub('q2')] })

  const { container } = render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const maxInput = (await screen.findByRole('spinbutton', { name: /maximum/i })) as HTMLInputElement
  fireEvent.change(maxInput, { target: { value: '500' } })
  expect(maxInput.value).toBe(String(SINO_SYSTEM_INFO.maximum))

  // Next is locked until the question has a verdict, so q1 is answered before moving on.
  await waitForQuestion(container)
  await answerQuestion('1')
  await screen.findByRole('status')

  fireEvent.click(screen.getByRole('button', { name: /next/i }))

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(questionCreationRequests(fetchMock)[1].body).toEqual(
    expect.objectContaining({ maximum: SINO_SYSTEM_INFO.maximum }),
  )
})

test('switching systems drops a custom maximum override in favour of the new systems catalogue default', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1'), questionStub('q2')] })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const maxInput = (await screen.findByRole('spinbutton', { name: /maximum/i })) as HTMLInputElement
  fireEvent.change(maxInput, { target: { value: '10' } })

  const selector = (await screen.findByRole('combobox', { name: /system/i })) as HTMLSelectElement
  fireEvent.change(selector, { target: { value: 'native' } })

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  // If a leftover override survived the system switch, this would send `maximum: 10`
  // instead of native Korean's own catalogue maximum (99) - a real bug the range-bounds
  // test above cannot catch, since it never types into the control before switching.
  expect(questionCreationRequests(fetchMock)[1].body).toEqual(
    expect.objectContaining({ system: 'native', maximum: NATIVE_SYSTEM_INFO.maximum }),
  )

  await waitFor(() => {
    const rangeInput = screen.getByRole('spinbutton', { name: /maximum/i }) as HTMLInputElement
    expect(rangeInput.value).toBe(String(NATIVE_SYSTEM_INFO.maximum))
  })
})

test('the replay and show-answer controls and the audio element stay unusable until the first question has loaded', async () => {
  // A bespoke fetch mock, not `stubFetch`: this test needs to observe the gap between the
  // systems catalogue arriving and the first create-question call resolving, which
  // `stubFetch`'s all-at-once promises can't hold open. `resolveQuestion` defaults to a
  // throwing stub rather than `null`, so the type stays a plain `() => void` throughout
  // (TypeScript cannot narrow a variable reassigned only from inside a closure back from
  // `null`, so a nullable holder here would need a non-null assertion at the call site).
  let resolveQuestion: () => void = () => {
    throw new Error('the create-question call never fired')
  }
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && url.endsWith(SYSTEMS_PATH)) {
      return Promise.resolve(jsonResponse(DEFAULT_SYSTEMS_RESPONSE))
    }
    if (method === 'POST' && url.endsWith(QUESTIONS_PATH)) {
      return new Promise((resolve) => {
        resolveQuestion = () => resolve(jsonResponse(questionStub('q1')))
      })
    }
    throw new Error(`Unhandled fetch in test: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  const { container } = render(<App />)

  const replayButton = await screen.findByRole('button', { name: /replay/i })
  expect(replayButton.hasAttribute('disabled')).toBe(true)
  expect(showAnswerButton().disabled).toBe(true)
  expect(container.querySelector('audio')).toBeNull()

  // The draw is sent by an effect that can run a task after Replay first renders.
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
  resolveQuestion()

  await waitFor(() => expect(replayButton.hasAttribute('disabled')).toBe(false))
  expect(showAnswerButton().disabled).toBe(false)
  expect(container.querySelector('audio')?.getAttribute('src')).toBe(
    '/api/exercises/numbers/questions/q1/audio',
  )
})

test('replay plays the same audio again without drawing a new question', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1')] })

  render(<App />)

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
  const replayButton = await screen.findByRole('button', { name: /replay/i })
  const playCallsBeforeReplay = playSpy.mock.calls.length

  fireEvent.click(replayButton)

  expect(playSpy.mock.calls.length).toBe(playCallsBeforeReplay + 1)
  expect(questionCreationRequests(fetchMock)).toHaveLength(1)
})

test('shows a correct verdict for a correct answer', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'correct', expected_number: 7, text: '칠' },
  })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  await answerQuestion('7')

  const status = await screen.findByRole('status')
  expect(status.textContent).toMatch(/\bcorrect\b/i)
})

test('shows an incorrect verdict naming both the expected number and its Korean text', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'incorrect', expected_number: 42, text: '마흔둘' },
  })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  await answerQuestion('41')

  const status = await screen.findByRole('status')
  expect(status.textContent).toMatch(/\bincorrect\b/i)
  expect(status.textContent).toContain('42')
  expect(status.textContent).toContain('마흔둘')
})

test('shows a not-a-number verdict, visibly distinct from a wrong answer', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'not_a_number', expected_number: 5, text: '오' },
  })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  await answerQuestion('abc')

  const status = await screen.findByRole('status')
  // A bare /correct/i would also match "incorrect" (it contains "correct" as a
  // substring) - the word-boundary form is what actually tells the three verdicts apart.
  expect(status.textContent).not.toMatch(/\bcorrect\b/i)
  expect(status.textContent).toMatch(/not.*number/i)
})

test('blocks submission while the answer input is empty', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1')] })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const submitButton = await screen.findByRole('button', { name: /submit/i })
  fireEvent.click(submitButton)

  expect(answerRequests(fetchMock)).toHaveLength(0)
})

test('pressing Enter in the answer input submits, the same as clicking submit', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'correct', expected_number: 3, text: '삼' },
  })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const answerInput = (await screen.findByRole('textbox', { name: /answer/i })) as HTMLInputElement
  fireEvent.change(answerInput, { target: { value: '3' } })
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })

  await waitFor(() => expect(answerRequests(fetchMock)).toHaveLength(1))
  expect(answerRequests(fetchMock)[0].body).toEqual({ answer: '3' })
})

// The whole loop on one key (asked by the user at the ui-redesign T03 sign-off): Enter
// submits, and once the verdict is shown, Enter again moves on to the next number.
test('pressing Enter again once the verdict is shown draws the next question instead of resubmitting', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'incorrect', expected_number: 3, text: '삼' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  const answerInput = (await screen.findByRole('textbox', { name: /answer/i })) as HTMLInputElement
  fireEvent.change(answerInput, { target: { value: '4' } })
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })
  await screen.findByRole('status')

  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(answerRequests(fetchMock)).toHaveLength(1)
  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q2/audio',
    )
  })
  expect(answerInput.value).toBe('')
  expect(screen.queryByRole('status')).toBeNull()
})

test('pressing Enter in the answer input after a reveal draws the next question', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'not_a_number', expected_number: 42, text: '사십이' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  fireEvent.click(showAnswerButton())
  await screen.findByRole('status')

  const answerInput = screen.getByRole('textbox', { name: /answer/i })
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(answerRequests(fetchMock)).toHaveLength(1)
})

// A mouse click on Submit or Show answer disables the button it lands on, which drops focus
// to the page itself: Enter still has to move on from there.
test.each([
  { name: 'clicking submit', act: () => answerQuestion('3') },
  {
    name: 'clicking show answer',
    act: () => {
      fireEvent.click(showAnswerButton())
      return Promise.resolve()
    },
  },
])('after $name, Enter moves on from wherever focus is left', async ({ act }) => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'incorrect', expected_number: 4, text: '사' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  await act()
  await screen.findByRole('status')
  fireEvent.keyDown(document.body, { key: 'Enter', code: 'Enter' })

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  expect(answerRequests(fetchMock)).toHaveLength(1)
})

test('Enter on the focused next button draws one question, not two', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2'), questionStub('q3')],
    answer: { verdict: 'correct', expected_number: 3, text: '삼' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)
  await answerQuestion('3')
  await screen.findByRole('status')

  // `fireEvent` returns false when the default action was cancelled. On a focused button
  // that default is the browser clicking it, a second Next that jsdom does not simulate.
  nextButton().focus()
  expect(fireEvent.keyDown(nextButton(), { key: 'Enter', code: 'Enter' })).toBe(false)

  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q2/audio',
    )
  })
  expect(questionCreationRequests(fetchMock)).toHaveLength(2)
})

test('a held-down Enter does not skip past the verdict it just produced', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'incorrect', expected_number: 3, text: '삼' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  const answerInput = screen.getByRole('textbox', { name: /answer/i })
  fireEvent.change(answerInput, { target: { value: '4' } })
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })
  await screen.findByRole('status')

  // The same key, auto-repeating: moving on takes a fresh press.
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter', repeat: true })

  expect(questionCreationRequests(fetchMock)).toHaveLength(1)
  expect(answerRequests(fetchMock)).toHaveLength(1)
  expect(screen.getByRole('status')).toBeDefined()
})

test('next draws a new question and clears the input and the previous feedback', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'correct', expected_number: 9, text: '구' },
  })

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  await answerQuestion('9')
  await screen.findByRole('status')

  const nextButton = await screen.findByRole('button', { name: /next/i })
  fireEvent.click(nextButton)

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  const answerInput = (await screen.findByRole('textbox', { name: /answer/i })) as HTMLInputElement
  expect(answerInput.value).toBe('')
  const status = screen.queryByRole('status')
  expect(status === null || status.textContent === '').toBe(true)
})

test('keeps next disabled while the question has no verdict, even after typing an answer', async () => {
  stubFetch({ questions: [questionStub('q1')] })

  const { container } = render(<App />)
  await waitForQuestion(container)

  expect(nextButton().disabled).toBe(true)

  const answerInput = (await screen.findByRole('textbox', { name: /answer/i })) as HTMLInputElement
  fireEvent.change(answerInput, { target: { value: '7' } })

  expect(nextButton().disabled).toBe(true)
})

// `not_a_number` left this list when a typo stopped counting as an answer (user's request
// after the ui-redesign sign-off, 2026-09-21): see the not-a-number test just below.
test.each(['correct', 'incorrect'])(
  'enables next once submitting returns a %s verdict',
  async (verdict) => {
    const fetchMock = stubFetch({
      questions: [questionStub('q1')],
      answer: { verdict, expected_number: 12, text: '십이' },
    })

    const { container } = render(<App />)
    await waitForQuestion(container)
    // Locked first, so the unlock below is a change and not a button that was never locked.
    expect(nextButton().disabled).toBe(true)

    await answerQuestion('12')
    await screen.findByRole('status')

    expect(nextButton().disabled).toBe(false)
    expect(answerRequests(fetchMock)).toHaveLength(1)
  },
)

// A typo is not an answer: the question stays open, with no Next by button or by Enter,
// until the user types digits or reveals.
test('a not-a-number verdict keeps the question open: next locked, submit and show answer still usable', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'not_a_number', expected_number: 5, text: '오' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  await answerQuestion('abc')
  await screen.findByRole('status')

  expect(nextButton().disabled).toBe(true)
  expect(showAnswerButton().disabled).toBe(false)
  expect(submitButton().disabled).toBe(false)

  fireEvent.keyDown(document.body, { key: 'Enter', code: 'Enter' })
  expect(questionCreationRequests(fetchMock)).toHaveLength(1)

  // Enter in the answer field submits the retyped answer instead of moving on.
  const answerInput = screen.getByRole('textbox', { name: /answer/i })
  fireEvent.change(answerInput, { target: { value: '5' } })
  fireEvent.keyDown(answerInput, { key: 'Enter', code: 'Enter' })

  await waitFor(() => expect(answerRequests(fetchMock)).toHaveLength(2))
  expect(answerRequests(fetchMock)[1].body).toEqual({ answer: '5' })
  expect(questionCreationRequests(fetchMock)).toHaveLength(1)
})

test.each(['correct', 'incorrect'])(
  'blocks any further submission once a %s verdict is shown',
  async (verdict) => {
    const fetchMock = stubFetch({
      questions: [questionStub('q1')],
      answer: { verdict, expected_number: 12, text: '십이' },
    })

    const { container } = render(<App />)
    await waitForQuestion(container)
    await answerQuestion('12')
    await screen.findByRole('status')

    expect(submitButton().disabled).toBe(true)
    fireEvent.click(submitButton())

    expect(answerRequests(fetchMock)).toHaveLength(1)
  },
)

test('show answer judges an empty answer, then displays the answer as a miss and unlocks next', async () => {
  // The backend answers an empty string with `not_a_number` but still attaches the expected
  // number and its Korean text (`judge_answer`), which is all a reveal needs.
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'not_a_number', expected_number: 42, text: '사십이' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)
  expect(nextButton().disabled).toBe(true)

  fireEvent.click(showAnswerButton())

  const status = await screen.findByRole('status')
  expect(answerRequests(fetchMock)).toHaveLength(1)
  expect(answerRequests(fetchMock)[0].body).toEqual({ answer: '' })
  expect(status.textContent).toContain('42')
  expect(status.textContent).toContain('사십이')
  // Worded and styled as a miss: a reveal is neither a right answer nor a typo, so it must
  // read as neither "Correct!" nor "That is not a number".
  expect(status.textContent).toMatch(/answer was/i)
  expect(status.textContent).not.toMatch(/\bcorrect\b/i)
  expect(status.textContent).not.toMatch(/not.*number/i)
  // Styled as neither a right answer nor a typo: the neutral tone. This replaced two
  // assertions on `styles.css` classes (`feedback-incorrect`, `feedback-correct`) when the
  // page moved to the design primitives (ui-redesign T03, user's decision 2026-09-21).
  expect(status.dataset.tone).toBe('neutral')
  expect(nextButton().disabled).toBe(false)
})

test('show answer is disabled once a submitted answer already has a verdict', async () => {
  stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'incorrect', expected_number: 42, text: '사십이' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)
  expect(showAnswerButton().disabled).toBe(false)

  await answerQuestion('41')
  await screen.findByRole('status')

  expect(showAnswerButton().disabled).toBe(true)
})

test('show answer is one-shot: after it is used the button is disabled and sends nothing more', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'not_a_number', expected_number: 42, text: '사십이' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  fireEvent.click(showAnswerButton())
  await screen.findByRole('status')
  expect(showAnswerButton().disabled).toBe(true)

  fireEvent.click(showAnswerButton())

  expect(answerRequests(fetchMock)).toHaveLength(1)
})

test('next after a reveal draws a new question with a fresh, unrevealed state', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1'), questionStub('q2')],
    answer: { verdict: 'not_a_number', expected_number: 42, text: '사십이' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  fireEvent.click(showAnswerButton())
  await screen.findByRole('status')
  fireEvent.click(nextButton())

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
  await waitFor(() => {
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/exercises/numbers/questions/q2/audio',
    )
  })
  expect(screen.queryByRole('status')).toBeNull()
  // The new question starts locked again, with its own reveal available.
  expect(nextButton().disabled).toBe(true)
  expect(showAnswerButton().disabled).toBe(false)

  // A real submission on the new question must not inherit the reveal wording: with the
  // stub's `not_a_number` verdict it reads as a typo, not as "The answer was ...".
  await answerQuestion('abc')
  const status = await screen.findByRole('status')
  expect(status.textContent).toMatch(/not.*number/i)
  expect(status.textContent).not.toMatch(/answer was/i)
})

// This replaced "a submission after a reveal is worded as a submission again": typing the
// revealed number and submitting it would score a guess that was never made (user's
// request after the ui-redesign sign-off, 2026-09-21).
test('no answer can be submitted once the answer has been revealed', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'not_a_number', expected_number: 7, text: '칠' },
  })

  const { container } = render(<App />)
  await waitForQuestion(container)

  fireEvent.click(showAnswerButton())
  await screen.findByRole('status')

  await answerQuestion('7')

  expect(submitButton().disabled).toBe(true)
  expect(answerRequests(fetchMock)).toHaveLength(1)
  expect(screen.getByRole('status').textContent).toMatch(/answer was/i)
})

test('a failed reveal shows an error, keeps next locked and leaves show answer available to retry', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1')], answerRejects: true })

  const { container } = render(<App />)
  await waitForQuestion(container)

  fireEvent.click(showAnswerButton())

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBeTruthy()
  expect(answerRequests(fetchMock)).toHaveLength(1)
  // No verdict came back, so nothing is shown and nothing is unlocked: a flaky connection
  // must not turn into a way to skip a question.
  expect(screen.queryByRole('status')).toBeNull()
  expect(nextButton().disabled).toBe(true)
  expect(showAnswerButton().disabled).toBe(false)
})

test('after a failed draw next stays available, so the user can retry', async () => {
  // With no question in hand there is nothing to skip, and Next is the only retry control:
  // locking it here would strand the user on the error message until a reload.
  const fetchMock = stubFetch({ questionsRejects: true })

  render(<App />)
  await screen.findByRole('alert')
  expect(nextButton().disabled).toBe(false)

  fireEvent.click(nextButton())

  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(2))
})

test('shows a visible error message when the create-question request fails', async () => {
  stubFetch({ questionsRejects: true })

  render(<App />)

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBeTruthy()
  // The page is not blank: the rest of the shell is still there alongside the error.
  expect(screen.getByRole('heading', { name: 'Oral Korean' })).toBeDefined()
})

test('shows the backends own rejection message when creating a question is refused', async () => {
  // A bespoke mock: this is the one case where the backend answers but rejects the
  // request (422), as opposed to the network-level failure `questionsRejects` models.
  // `App` must surface the real detail text (e.g. the actual range a system supports),
  // not the generic "is the backend running?" message reserved for the case where the
  // backend genuinely cannot be reached.
  const detail = 'native-Korean questions can only be drawn from 1 to 99, so 1 to 500 is out of reach.'
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (method === 'GET' && url.endsWith(SYSTEMS_PATH)) {
      return Promise.resolve(jsonResponse(DEFAULT_SYSTEMS_RESPONSE))
    }
    if (method === 'POST' && url.endsWith(QUESTIONS_PATH)) {
      return Promise.resolve(jsonResponse({ detail }, 422))
    }
    throw new Error(`Unhandled fetch in test: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe(detail)
})

test('shows a visible error when submitting an answer fails, without discarding the current question', async () => {
  const fetchMock = stubFetch({ questions: [questionStub('q1')], answerRejects: true })

  const { container } = render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))
  await waitFor(() => expect(container.querySelector('audio')).not.toBeNull())
  const audioSrcBeforeSubmit = container.querySelector('audio')?.getAttribute('src')

  await answerQuestion('7')

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBeTruthy()
  // A failed answer submission is not a correct/incorrect/not-a-number verdict: nothing
  // should render as feedback, and the still-valid question (and its audio) must survive
  // so the user can retry rather than losing their place.
  expect(screen.queryByRole('status')).toBeNull()
  expect(container.querySelector('audio')?.getAttribute('src')).toBe(audioSrcBeforeSubmit)
  expect(answerRequests(fetchMock)).toHaveLength(1)
})

test('shows a visible error, not a blank page, when the systems catalogue itself fails to load', async () => {
  stubFetch({ systemsRejects: true })

  render(<App />)

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Oral Korean' })).toBeDefined()
  // Distinct failure mode from a failed create-question: the catalogue never arrived, so
  // there is structurally nothing to build the selector, range control or question from -
  // the page is expected to stay on its loading message rather than show a broken form.
  expect(screen.queryByRole('combobox')).toBeNull()
})

test('never reveals the drawn number or its Korean text before an answer is submitted or revealed', async () => {
  const fetchMock = stubFetch({
    questions: [questionStub('q1')],
    answer: { verdict: 'correct', expected_number: 17, text: '열일곱' },
  })

  const { container } = render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  // The create-question stub above only ever returns `question_id` and `audio_url` (see
  // `questionStub`), so there is structurally nothing for the component to leak here -
  // this also checks that nothing eagerly calls the answer endpoint before submission.
  expect(container.innerHTML).not.toContain('17')
  expect(container.innerHTML).not.toContain('열일곱')
  expect(answerRequests(fetchMock)).toHaveLength(0)

  // The one other way the answer can arrive is Show answer, and it is a deliberate user
  // action exactly like Submit: absent until it is clicked, present once it has been.
  fireEvent.click(showAnswerButton())
  await screen.findByRole('status')
  expect(container.innerHTML).toContain('17')
  expect(container.innerHTML).toContain('열일곱')
  expect(answerRequests(fetchMock)).toHaveLength(1)
})

/*
 * ui-redesign T03: the page is now built from the design primitives in `components/`,
 * with no behaviour change. vitest replaces CSS with empty strings and jsdom has no
 * layout, so these pin only what the markup can show: roles and names, input attributes,
 * `lang`, which icon each verdict gets, `tabindex`, and the `motion-safe:` guard.
 */

interface VerdictScenario {
  name: string
  answer: { verdict: string; expected_number: number; text: string }
  act: () => Promise<void>
}

const VERDICT_SCENARIOS: VerdictScenario[] = [
  {
    name: 'correct',
    answer: { verdict: 'correct', expected_number: 7, text: '칠' },
    act: () => answerQuestion('7'),
  },
  {
    name: 'incorrect',
    answer: { verdict: 'incorrect', expected_number: 42, text: '마흔둘' },
    act: () => answerQuestion('41'),
  },
  {
    name: 'not a number',
    answer: { verdict: 'not_a_number', expected_number: 5, text: '오' },
    act: () => answerQuestion('abc'),
  },
  {
    name: 'revealed',
    answer: { verdict: 'not_a_number', expected_number: 42, text: '마흔둘' },
    act: () => {
      fireEvent.click(showAnswerButton())
      return Promise.resolve()
    },
  },
]

/** Renders the page, waits for the first question, then produces the scenario's verdict. */
async function renderVerdict(
  scenario: VerdictScenario,
): Promise<{ container: HTMLElement; status: HTMLElement }> {
  stubFetch({ questions: [questionStub('q1')], answer: scenario.answer })
  const { container } = render(<App />)
  await waitForQuestion(container)
  await scenario.act()
  const status = await screen.findByRole('status')
  return { container, status }
}

function elementsWithPositiveTabindex(container: HTMLElement): Element[] {
  return [...container.querySelectorAll('[tabindex]')].filter(
    (element) => Number(element.getAttribute('tabindex')) > 0,
  )
}

test('keeps every control role and accessible name once the first question has loaded', async () => {
  stubFetch()

  const { container } = render(<App />)
  await waitForQuestion(container)

  expect(screen.getByRole('heading', { name: 'Oral Korean' }).textContent).toBe('Oral Korean')
  const selector = screen.getByRole('combobox', { name: /system/i })
  expect(within(selector).getByRole('option', { name: /sino-korean/i })).toBeDefined()
  expect(within(selector).getByRole('option', { name: /native korean/i })).toBeDefined()
  expect(screen.getByRole('spinbutton', { name: /maximum/i })).toBeDefined()
  expect(screen.getByRole('textbox', { name: /answer/i })).toBeDefined()
  for (const name of [/replay/i, /submit/i, /next/i, /show answer/i]) {
    expect(screen.getByRole('button', { name })).toBeDefined()
  }
})

test('the answer field opens a digit keypad on phones and still accepts free text', async () => {
  stubFetch()

  render(<App />)

  const answerInput = await screen.findByRole('textbox', { name: /answer/i })
  // `type="text"` is load-bearing: a number input would sanitise "abc" away before the
  // not-a-number verdict could ever be reached.
  expect(answerInput.getAttribute('type')).toBe('text')
  expect(answerInput.getAttribute('inputmode')).toBe('numeric')
})

test.each(VERDICT_SCENARIOS.filter((scenario) => ['incorrect', 'revealed'].includes(scenario.name)))(
  'marks the Korean reading as Korean in the $name feedback',
  async (scenario) => {
    const { status } = await renderVerdict(scenario)

    const korean = status.querySelectorAll('[lang="ko"]')
    expect(korean).toHaveLength(1)
    expect(korean[0].textContent).toBe('마흔둘')
  },
)

test('gives each of the four verdicts its own icon, so they stay distinct without colour', async () => {
  const iconMarkup: string[] = []
  for (const scenario of VERDICT_SCENARIOS) {
    const { status } = await renderVerdict(scenario)
    const icon = status.querySelector('svg')
    if (icon === null) {
      throw new Error(`the ${scenario.name} verdict rendered no icon`)
    }
    iconMarkup.push(icon.outerHTML)
    cleanup()
    vi.unstubAllGlobals()
  }

  expect(new Set(iconMarkup).size).toBe(VERDICT_SCENARIOS.length)
})

test('no element has a positive tabindex, so tab order is DOM order, before and after a verdict', async () => {
  stubFetch({ questions: [questionStub('q1')], answer: VERDICT_SCENARIOS[0].answer })
  const { container } = render(<App />)
  await waitForQuestion(container)
  expect(elementsWithPositiveTabindex(container)).toEqual([])

  await answerQuestion('7')
  await screen.findByRole('status')
  expect(elementsWithPositiveTabindex(container)).toEqual([])
})

test.each(VERDICT_SCENARIOS)(
  'applies feedback animations only through motion-safe: after a $name verdict',
  async (scenario) => {
    const { container } = await renderVerdict(scenario)

    const animationTokens = classTokensIn(container).filter((token) => token.includes('animate-'))
    // Not vacuous: every verdict has an entrance animation to guard.
    expect(animationTokens.length).toBeGreaterThan(0)
    for (const token of animationTokens) {
      expect(token.startsWith('motion-safe:')).toBe(true)
    }
  },
)
