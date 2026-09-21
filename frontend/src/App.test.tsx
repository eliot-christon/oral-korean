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
 *     /next/i respectively.
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

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const maxInput = (await screen.findByRole('spinbutton', { name: /maximum/i })) as HTMLInputElement
  fireEvent.change(maxInput, { target: { value: '10' } })
  expect(maxInput.value).toBe('10')

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

  render(<App />)
  await waitFor(() => expect(questionCreationRequests(fetchMock)).toHaveLength(1))

  const maxInput = (await screen.findByRole('spinbutton', { name: /maximum/i })) as HTMLInputElement
  fireEvent.change(maxInput, { target: { value: '500' } })
  expect(maxInput.value).toBe(String(SINO_SYSTEM_INFO.maximum))

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

test('the replay control and the audio element stay unusable until the first question has loaded', async () => {
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
  expect(container.querySelector('audio')).toBeNull()

  resolveQuestion()

  await waitFor(() => expect(replayButton.hasAttribute('disabled')).toBe(false))
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

test('never reveals the drawn number or its Korean text before an answer is submitted', async () => {
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
})
