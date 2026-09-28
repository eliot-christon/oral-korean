/**
 * Tests for the learn and review sessions page (vocab-sessions T04), against the ticket's test
 * contract.
 *
 * `fetch` is stubbed with canned responses shaped like `src/oral_korean/api/routes/
 * vocab_sessions.py`: a question carries only its documented fields, so a page that needed
 * the answer before submitting could not render. `HTMLMediaElement.prototype.play` is stubbed
 * (jsdom has none) and `Date` is faked, so "in 3 days" reads the same every run. Same
 * conventions as `NumbersPage.test.tsx`: explicit `cleanup()`, no jest-dom matcher.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { jsonResponse, NEW_WORD_STATISTICS } from '../testUtils'
import { SessionPage } from './SessionPage'

const NOW = new Date('2026-09-26T10:00:00Z')

const PROGRESS = { done: 0, total: 2, questions_done: 0, question_total: 2 }

const PRESENTATION = {
  type: 'presentation',
  item_id: 'p1',
  korean: '사과',
  translations: ['apple', 'pomme'],
  audio_url: '/api/vocab/items/p1/audio',
  progress: PROGRESS,
}

const CHOICE_QUESTION = {
  type: 'question',
  item_id: 'q1',
  direction: 'hangul_to_translation',
  mode: 'choice',
  prompt: '사과',
  audio_url: null,
  options: ['pear', 'apple; pomme', 'grape', 'persimmon'],
  scored: true,
  progress: PROGRESS,
}

const VOICE_TYPING_QUESTION = {
  type: 'question',
  item_id: 'q2',
  direction: 'voice_to_translation',
  mode: 'typing',
  prompt: null,
  audio_url: '/api/vocab/items/q2/audio',
  options: null,
  scored: true,
  progress: PROGRESS,
}

const HANGUL_TYPING_QUESTION = {
  type: 'question',
  item_id: 'q3',
  direction: 'translation_to_hangul',
  mode: 'typing',
  prompt: 'apple; pomme',
  audio_url: null,
  options: null,
  scored: true,
  progress: PROGRESS,
}

const PRACTICE_QUESTION = { ...HANGUL_TYPING_QUESTION, item_id: 'q4', scored: false }

const KNOWN = {
  ...NEW_WORD_STATISTICS,
  score: 54,
  stability: 9.2,
  phase: 'review',
  next_review: '2026-10-05T10:00:00Z',
  last_review: '2026-09-17T10:00:00Z',
  due: false,
  review_count: 3,
}

const LAPSED = {
  ...KNOWN,
  score: 14,
  stability: 1.3,
  next_review: '2026-09-27T10:00:00Z',
  last_review: '2026-09-26T10:00:00Z',
  review_count: 4,
  lapse_count: 1,
}

const WRONG_SCORED = {
  correct: false,
  korean: '사과',
  translations: ['apple', 'pomme'],
  correct_option: 'apple; pomme',
  scored: true,
  statistics_before: KNOWN,
  statistics_after: LAPSED,
}

const RIGHT_PRACTICE = {
  correct: true,
  korean: '사과',
  translations: ['apple', 'pomme'],
  correct_option: null,
  scored: false,
  statistics_before: LAPSED,
  statistics_after: LAPSED,
}

const END = {
  type: 'end',
  summary: {
    words: [
      {
        korean: '사과',
        translations: ['apple', 'pomme'],
        correct: false,
        directions: [{ direction: 'hangul_to_translation', correct: false }],
      },
      {
        korean: '배',
        translations: ['pear'],
        correct: true,
        directions: [{ direction: 'hangul_to_translation', correct: true }],
      },
    ],
    word_count: 2,
    correct_count: 1,
    question_count: 2,
    correct_question_count: 1,
  },
}

/** The one word of the start form's learn queue and review picker (vocab-directions T04). */
const QUEUED = { id: 7, korean: '포도', translations: ['grape'], tags: [] }

type Reply = { status: number; body: unknown } | Promise<{ status: number; body: unknown }>

interface Stub {
  start?: Reply
  next?: Reply[]
  answer?: Reply[]
}

/** Routes each request to its canned reply; `next` and `answer` replies are used in order. */
function stubFetch(stub: Stub): ReturnType<typeof vi.fn> {
  const nexts = [...(stub.next ?? [])]
  const answers = [...(stub.answer ?? [])]
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    let reply: Reply | undefined
    if (url === '/api/vocab/tags') {
      reply = { status: 200, body: { tags: [{ tag: 'food', count: 2 }] } }
    } else if (url.startsWith('/api/vocab/words')) {
      reply = { status: 200, body: { words: [], summary: { total: 3, new: 2, due: 1, average_score: 40 } } }
    } else if (url.startsWith('/api/vocab/learn-queue')) {
      reply = { status: 200, body: { words: [QUEUED] } }
    } else if (url.startsWith('/api/vocab/review-candidates')) {
      reply = { status: 200, body: { words: [{ ...QUEUED, due: true, next_review: '2026-09-25T10:00:00Z' }] } }
    } else if (url === '/api/vocab/sessions') {
      reply = stub.start ?? { status: 201, body: { session_id: 's1', kind: 'review', word_count: 2, directions: [] } }
    } else if (url === '/api/vocab/sessions/s1/next') {
      reply = nexts.shift()
    } else if (url.endsWith('/answer')) {
      reply = answers.shift()
    }
    if (reply === undefined) {
      throw new Error(`Unhandled fetch in test: ${url}`)
    }
    const { status, body } = await reply
    return jsonResponse(body, status)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function ok(body: unknown): Reply {
  return { status: 200, body }
}

function requestsTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string): RequestInit[] {
  return fetchMock.mock.calls
    .filter((call) => String(call[0]).endsWith(suffix))
    .map((call) => (call[1] ?? {}) as RequestInit)
}

function bodiesSentTo(fetchMock: ReturnType<typeof vi.fn>, suffix: string): unknown[] {
  return requestsTo(fetchMock, suffix).map((init) => JSON.parse(String(init.body)) as unknown)
}

function button(name: string | RegExp): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement
}

/** Renders the page and starts a session with the defaults; resolves once the first item shows. */
async function startedSession(kind: 'learn' | 'review' = 'review'): Promise<void> {
  render(<SessionPage kind={kind} />)
  await screen.findByText(kind === 'learn' ? '2 new words' : '1 word due')
  // The learn queue or the review picker is in: a review then starts over the words it chose.
  await screen.findByRole('list', { name: kind === 'learn' ? 'Learn queue' : 'Words to review' })
  fireEvent.click(button('Start'))
}

let playSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(NOW)
  playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  playSpy.mockRestore()
})

// ---------------------------------------------------------------------------------
// Starting
// ---------------------------------------------------------------------------------

test('the start form counts the words the session could take, from the word list', async () => {
  stubFetch({})

  render(<SessionPage kind="learn" />)

  expect(await screen.findByText('2 new words')).toBeDefined()
  expect(screen.getByRole('heading', { name: 'Learn new words' })).toBeDefined()
})

test('starting with the defaults sends the kind, all four directions and the words picked, no tag and no size', async () => {
  const fetchMock = stubFetch({ next: [ok(CHOICE_QUESTION)] })

  await startedSession('review')

  await screen.findByText('What does it mean?')
  expect(bodiesSentTo(fetchMock, '/api/vocab/sessions')).toEqual([
    {
      kind: 'review',
      directions: [
        'hangul_to_translation',
        'translation_to_hangul',
        'voice_to_hangul',
        'voice_to_translation',
      ],
      word_ids: [7],
    },
  ])
})

test('unticking both voice directions sends only the written ones, with the tag and size chosen', async () => {
  const fetchMock = stubFetch({ next: [ok(CHOICE_QUESTION)] })
  render(<SessionPage kind="review" />)
  await screen.findByRole('option', { name: 'food' })

  fireEvent.click(screen.getByRole('checkbox', { name: 'Voice to Hangul' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Voice to translation' }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Tag' }), { target: { value: 'food' } })
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } })
  fireEvent.click(button('Start'))

  await screen.findByText('What does it mean?')
  expect(bodiesSentTo(fetchMock, '/api/vocab/sessions')).toEqual([
    { kind: 'review', directions: ['hangul_to_translation', 'translation_to_hangul'], tag: 'food', size: 3 },
  ])
})

test('unticking all four directions disables Start', async () => {
  stubFetch({})
  render(<SessionPage kind="review" />)

  for (const checkbox of screen.getAllByRole('checkbox')) {
    fireEvent.click(checkbox)
  }

  expect(button('Start').disabled).toBe(true)
})

test('nothing to review shows the backend message and a link to the word list', async () => {
  stubFetch({ start: { status: 409, body: { detail: 'Nothing to review.' } } })

  await startedSession('review')

  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toBe('Nothing to review.')
  expect(screen.getByRole('link', { name: 'Go to your words' }).getAttribute('href')).toBe('#/words')
})

// ---------------------------------------------------------------------------------
// Presentations and questions
// ---------------------------------------------------------------------------------

test('a presentation shows the Korean as Korean and the translations, plays, and Continue moves on', async () => {
  const fetchMock = stubFetch({ next: [ok(PRESENTATION), ok(CHOICE_QUESTION)] })

  await startedSession('learn')

  const korean = await screen.findByText('사과')
  expect(korean.getAttribute('lang')).toBe('ko')
  expect(screen.getByText('apple; pomme')).toBeDefined()
  const playsBefore = playSpy.mock.calls.length
  fireEvent.click(button('Play the word'))
  expect(playSpy.mock.calls.length).toBe(playsBefore + 1)

  fireEvent.click(button('Continue'))

  await screen.findByText('What does it mean?')
  expect(requestsTo(fetchMock, '/api/vocab/sessions/s1/next')).toHaveLength(2)
})

test('a choice question answers with one tap, and the controls stay disabled until the verdict', async () => {
  let deliver: (reply: { status: number; body: unknown }) => void = () => {}
  const verdict = new Promise<{ status: number; body: unknown }>((resolve) => {
    deliver = resolve
  })
  const fetchMock = stubFetch({ next: [ok(CHOICE_QUESTION)], answer: [verdict] })
  await startedSession()

  expect((await screen.findByText('사과', { selector: 'p' })).getAttribute('lang')).toBe('ko')
  const options = CHOICE_QUESTION.options.map((option) => button(option))
  expect(options).toHaveLength(4)

  fireEvent.click(button('grape'))
  await waitFor(() => expect(button('grape').disabled).toBe(true))
  fireEvent.click(button('apple; pomme'))
  expect(button("I don't know").disabled).toBe(true)
  deliver({ status: 200, body: WRONG_SCORED })

  await screen.findByText('Not this time.')
  expect(bodiesSentTo(fetchMock, '/answer')).toEqual([{ choice: 2 }])
  expect(requestsTo(fetchMock, '/api/vocab/items/q1/answer')).toHaveLength(1)
})

test('a voice question shows no Korean before the answer, only a play button', async () => {
  // The stub carries only the documented fields: nothing to leak, and the page needs no more.
  expect(Object.keys(VOICE_TYPING_QUESTION).sort()).toEqual(
    ['audio_url', 'direction', 'item_id', 'mode', 'options', 'progress', 'prompt', 'scored', 'type'],
  )
  stubFetch({ next: [ok(VOICE_TYPING_QUESTION)], answer: [ok(WRONG_SCORED)] })
  const { container } = render(<SessionPage kind="review" />)
  await screen.findByText('1 word due')
  fireEvent.click(button('Start'))

  await screen.findByText('Listen: what does it mean?')
  expect(button('Play the word')).toBeDefined()
  expect(container.innerHTML).not.toContain('사과')
  expect(container.innerHTML).not.toContain('apple')

  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'pear' } })
  fireEvent.click(button('Submit'))

  await screen.findByText('Not this time.')
  expect(container.innerHTML).toContain('사과')
})

test('a Hangul answer field is Korean, and sends the text exactly as typed', async () => {
  const fetchMock = stubFetch({ next: [ok(HANGUL_TYPING_QUESTION)], answer: [ok(WRONG_SCORED)] })
  await startedSession()

  const field = await screen.findByRole('textbox', { name: 'Your answer, in Korean' })
  expect(field.getAttribute('lang')).toBe('ko')
  expect(field.getAttribute('autocapitalize')).toBe('off')
  expect(field.getAttribute('autocomplete')).toBe('off')
  expect(field.getAttribute('spellcheck')).toBe('false')
  fireEvent.change(field, { target: { value: ' 사 과 ' } })
  fireEvent.click(button('Submit'))

  await screen.findByText('Not this time.')
  expect(bodiesSentTo(fetchMock, '/answer')).toEqual([{ answer: ' 사 과 ' }])
})

test('a translation answer field is not marked Korean', async () => {
  stubFetch({ next: [ok(VOICE_TYPING_QUESTION)] })
  await startedSession()

  const field = await screen.findByRole('textbox', { name: 'Your answer' })
  expect(field.getAttribute('lang')).toBeNull()
  expect(field.getAttribute('autocapitalize')).toBe('off')
})

test('Enter while an input method is composing does not submit; a plain Enter does', async () => {
  const fetchMock = stubFetch({ next: [ok(HANGUL_TYPING_QUESTION)], answer: [ok(WRONG_SCORED)] })
  await startedSession()
  const field = await screen.findByRole('textbox', { name: 'Your answer, in Korean' })
  fireEvent.change(field, { target: { value: '사과' } })

  fireEvent.keyDown(field, { key: 'Enter', isComposing: true })
  fireEvent.keyDown(field, { key: 'Enter', keyCode: 229 })
  expect(requestsTo(fetchMock, '/answer')).toHaveLength(0)

  fireEvent.keyDown(field, { key: 'Enter' })

  await screen.findByText('Not this time.')
  expect(bodiesSentTo(fetchMock, '/answer')).toEqual([{ answer: '사과' }])
})

test.each([
  ['choice', CHOICE_QUESTION],
  ['typing', HANGUL_TYPING_QUESTION],
])("I don't know sends dont_know in %s mode", async (_mode, question) => {
  const fetchMock = stubFetch({ next: [ok(question)], answer: [ok(WRONG_SCORED)] })
  await startedSession()

  fireEvent.click(await screen.findByRole('button', { name: "I don't know" }))

  await screen.findByText('Not this time.')
  expect(bodiesSentTo(fetchMock, '/answer')).toEqual([{ dont_know: true }])
})

// ---------------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------------

test('a wrong scored answer shows the word, the right option, and the score and next review moving', async () => {
  stubFetch({ next: [ok(CHOICE_QUESTION)], answer: [ok(WRONG_SCORED)] })
  await startedSession()
  fireEvent.click(await screen.findByRole('button', { name: 'grape' }))

  const verdict = await screen.findByRole('status')
  expect(verdict.textContent).toContain('사과: apple; pomme')
  expect(verdict.querySelector('[lang="ko"]')?.textContent).toBe('사과')
  expect(verdict.textContent).toContain('The right answer: apple; pomme')
  expect(screen.getByText('54% → 14%')).toBeDefined()
  expect(screen.getByText('9.2 days → 1.3 days')).toBeDefined()
  expect(screen.getByText('in 1 day (was in 9 days)')).toBeDefined()
})

test('a practice answer says it was not scored and shows no before and after', async () => {
  stubFetch({ next: [ok(PRACTICE_QUESTION)], answer: [ok(RIGHT_PRACTICE)] })
  await startedSession()
  expect(await screen.findByText('Practice: not scored')).toBeDefined()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '사과' } })
  fireEvent.click(button('Submit'))

  await screen.findByText('Right!')
  expect(screen.getByText('Practice question: not scored.')).toBeDefined()
  expect(screen.queryByText('Score')).toBeNull()
})

test('Next, or Enter once the verdict is shown, asks for the next item', async () => {
  const fetchMock = stubFetch({
    next: [ok(CHOICE_QUESTION), ok(HANGUL_TYPING_QUESTION), ok(END)],
    answer: [ok(WRONG_SCORED), ok(WRONG_SCORED)],
  })
  await startedSession()
  fireEvent.click(await screen.findByRole('button', { name: 'grape' }))
  await screen.findByText('Not this time.')

  fireEvent.click(button('Next'))
  const field = await screen.findByRole('textbox', { name: 'Your answer, in Korean' })
  fireEvent.change(field, { target: { value: '배' } })
  fireEvent.keyDown(field, { key: 'Enter' })
  await screen.findByText('Not this time.')
  fireEvent.keyDown(window, { key: 'Enter', isComposing: true })
  expect(requestsTo(fetchMock, '/api/vocab/sessions/s1/next')).toHaveLength(2)
  fireEvent.keyDown(window, { key: 'Enter' })

  await screen.findByText('Session complete')
  expect(requestsTo(fetchMock, '/api/vocab/sessions/s1/next')).toHaveLength(3)
})

// ---------------------------------------------------------------------------------
// Failures and the end
// ---------------------------------------------------------------------------------

test('a 502 on next shows the backend message and Retry asks again', async () => {
  const detail = 'Could not synthesise audio for this question.'
  const fetchMock = stubFetch({
    next: [{ status: 502, body: { detail } }, ok(VOICE_TYPING_QUESTION)],
  })
  await startedSession()

  expect((await screen.findByRole('alert')).textContent).toBe(detail)
  fireEvent.click(button('Retry'))

  await screen.findByText('Listen: what does it mean?')
  expect(requestsTo(fetchMock, '/api/vocab/sessions/s1/next')).toHaveLength(2)
})

test('a 404 on answer says the session has ended and offers a new one', async () => {
  stubFetch({
    next: [ok(CHOICE_QUESTION)],
    answer: [{ status: 404, body: { detail: "No item with id 'q1'." } }],
  })
  await startedSession()
  fireEvent.click(await screen.findByRole('button', { name: 'grape' }))

  expect((await screen.findByRole('alert')).textContent).toBe('This session has ended.')
  fireEvent.click(button('Start a new session'))

  expect(await screen.findByRole('button', { name: 'Start' })).toBeDefined()
})

test('another failure on answer is an alert, and the question can be answered again', async () => {
  stubFetch({
    next: [ok(CHOICE_QUESTION)],
    answer: [{ status: 500, body: null }, ok(WRONG_SCORED)],
  })
  await startedSession()
  fireEvent.click(await screen.findByRole('button', { name: 'grape' }))

  expect((await screen.findByRole('alert')).textContent).toBe('Could not submit the answer.')
  await waitFor(() => expect(button('grape').disabled).toBe(false))
  fireEvent.click(button('grape'))

  expect(await screen.findByText('Not this time.')).toBeDefined()
})

test('the end shows the summary, a link to the word list and a way to start again', async () => {
  stubFetch({ next: [ok(END)] })
  await startedSession()

  expect(
    await screen.findByText(
      '1 of 2 words right in every direction, 1 of 2 questions right at the first try',
    ),
  ).toBeDefined()
  expect(screen.getByText('missed')).toBeDefined()
  expect(screen.getByText('right')).toBeDefined()
  expect(screen.getByRole('link', { name: 'See your words' }).getAttribute('href')).toBe('#/words')
  fireEvent.click(button('Start another session'))

  expect(await screen.findByRole('button', { name: 'Start' })).toBeDefined()
})

// ---------------------------------------------------------------------------------
// Per direction (vocab-directions T05)
// ---------------------------------------------------------------------------------

test('progress reads in words and in questions', async () => {
  const progress = { done: 1, total: 3, questions_done: 5, question_total: 10 }
  stubFetch({ next: [ok({ ...CHOICE_QUESTION, progress })] })
  await startedSession()

  expect(await screen.findByText('1 of 3 words done, 5 of 10 questions')).toBeDefined()
})

test('the score change names the direction it belongs to', async () => {
  const question = {
    ...CHOICE_QUESTION,
    direction: 'voice_to_hangul',
    prompt: null,
    audio_url: '/api/vocab/items/q1/audio',
    options: ['배', '사과', '감', '포도'],
  }
  const verdict = {
    ...WRONG_SCORED,
    correct: true,
    correct_option: '사과',
    statistics_before: { ...LAPSED, score: 14 },
    statistics_after: { ...KNOWN, score: 30 },
  }
  stubFetch({ next: [ok(question)], answer: [ok(verdict)] })
  await startedSession()

  fireEvent.click(await screen.findByRole('button', { name: '사과' }))

  expect(await screen.findByText('14% → 30%')).toBeDefined()
  expect(screen.getByText('Voice to Hangul')).toBeDefined()
})

test('the summary lists a word once, with each direction and its verdict in words', async () => {
  const end = {
    type: 'end',
    summary: {
      words: [
        {
          korean: '사과',
          translations: ['apple'],
          correct: false,
          directions: [
            { direction: 'hangul_to_translation', correct: true },
            { direction: 'voice_to_hangul', correct: false },
          ],
        },
      ],
      word_count: 1,
      correct_count: 0,
      question_count: 2,
      correct_question_count: 1,
    },
  }
  stubFetch({ next: [ok(end)] })
  await startedSession()

  expect(
    await screen.findByText('0 of 1 word right in every direction, 1 of 2 questions right at the first try'),
  ).toBeDefined()
  expect(screen.getAllByText('사과')).toHaveLength(1)
  const rows = screen.getAllByRole('listitem').filter((item) => item.querySelector('ul') === null)
  expect(rows.map((row) => row.textContent)).toEqual([
    'Hangul to translation:right',
    'Voice to Hangul:missed',
  ])
})
