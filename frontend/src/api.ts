/**
 * Typed wrappers around the backend's HTTP API: the numbers exercise
 * (`src/oral_korean/api/routes/numbers.py`), the vocabulary
 * (`src/oral_korean/api/routes/vocab_words.py`) and its learn and review sessions
 * (`src/oral_korean/api/routes/vocab_sessions.py`).
 *
 * Unions are string unions rather than TypeScript `enum`s: `tsconfig.app.json` sets
 * `erasableSyntaxOnly`, which rejects real `enum` declarations because they are not erasable.
 *
 * Keep each path one self-contained literal, with `${...}` only for a path parameter and
 * any query string built outside it: `tests/test_frontend_assets.py` matches these
 * literals against the backend's registered routes.
 */

export type NumeralSystem = 'sino' | 'native'

export interface NumeralSystemInfo {
  system: NumeralSystem
  minimum: number
  maximum: number
}

export interface SystemsResponse {
  systems: NumeralSystemInfo[]
}

export interface CreateQuestionParams {
  system: NumeralSystem
  maximum: number
}

export interface CreateQuestionResponse {
  question_id: string
  audio_url: string
  system: NumeralSystem
}

export type Verdict = 'correct' | 'incorrect' | 'not_a_number'

export interface AnswerResponse {
  verdict: Verdict
  expected_number: number
  text: string
}

/** A response's body as JSON, or `null` when it has none or it is not JSON. */
async function bodyOf(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown
  } catch {
    return null
  }
}

/** A FastAPI error body's `detail`, whatever its shape, or `undefined` when there is none. */
function detailOf(body: unknown): unknown {
  return body !== null && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined
}

/**
 * Reads a FastAPI error body's `detail` field, when it is a plain string (as the numbers
 * routes send for a range/synthesis failure - see `_synthesise_or_502` and
 * `InvalidRangeError` handling in `routes/numbers.py` - and the vocabulary routes for a
 * refused word). Falls back to `fallback` when the body is not JSON or `detail` is not a
 * string (pydantic's own validation errors send a list, which is not a fact worth showing
 * verbatim to the user).
 */
async function errorDetail(response: Response, fallback: string): Promise<string> {
  const detail = detailOf(await bodyOf(response))
  return typeof detail === 'string' ? detail : fallback
}

/** A refused request: the message to show, and the HTTP status for a caller that tells them apart. */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * What to show for a failed request: the backend's own words when it answered with a
 * refusal, and a plain "cannot reach it" otherwise (a network error's own message,
 * "Failed to fetch", means nothing to the user).
 */
export function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Could not reach the backend. Is it running?'
}

async function parseJsonOrThrow<T>(response: Response, failureMessage: string): Promise<T> {
  if (!response.ok) {
    throw new ApiError(await errorDetail(response, failureMessage), response.status)
  }
  return (await response.json()) as T
}

export async function fetchSystems(): Promise<SystemsResponse> {
  const response = await fetch('/api/exercises/numbers/systems')
  return parseJsonOrThrow<SystemsResponse>(response, 'Could not load the numeral systems.')
}

export async function createQuestion(
  params: CreateQuestionParams,
): Promise<CreateQuestionResponse> {
  const response = await fetch('/api/exercises/numbers/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return parseJsonOrThrow<CreateQuestionResponse>(response, 'Could not draw a new question.')
}

export async function submitAnswer(questionId: string, answer: string): Promise<AnswerResponse> {
  const response = await fetch(`/api/exercises/numbers/questions/${questionId}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer }),
  })
  return parseJsonOrThrow<AnswerResponse>(response, 'Could not submit the answer.')
}

// The vocabulary. Every figure below is computed by the backend (`srs/` through the routes):
// the frontend formats them, never derives them.

export type Familiarity = 'new' | 'a_little' | 'well' | 'very_well'

export type Grade = 'again' | 'hard' | 'good' | 'easy'

export type Phase = 'new' | 'review'

/** Which side of a word is shown or spoken, and which side answers it. */
export type Direction =
  | 'hangul_to_translation'
  | 'translation_to_hangul'
  | 'voice_to_hangul'
  | 'voice_to_translation'

/** The four directions, in the backend's order: the order every per-direction list follows. */
export const DIRECTIONS: Direction[] = [
  'hangul_to_translation',
  'translation_to_hangul',
  'voice_to_hangul',
  'voice_to_translation',
]

export type AnswerMode = 'choice' | 'typing'

/**
 * Everything known about a word at the instant it was read. Every figure but the phase,
 * `due` and the counts is null for a new word. `score` and `recall` are whole percents;
 * `stability` is in days, `difficulty` from 1 to 10; dates are ISO 8601 in UTC.
 */
export interface WordStatistics {
  score: number | null
  recall: number | null
  stability: number | null
  difficulty: number | null
  phase: Phase
  next_review: string | null
  last_review: string | null
  due: boolean
  review_count: number
  lapse_count: number
}

export interface Word {
  id: number
  korean: string
  translations: string[]
  tags: string[]
  familiarity: Familiarity
  added_at: string
  /**
   * The word as a whole: the four directions' memories together. The score is the mean of
   * their strengths (a direction not learned yet counts 0), and recall, stability and
   * difficulty, which belong to one direction, are null.
   */
  statistics: WordStatistics
  /** Each direction's own memory, all four always present. */
  direction_statistics: Record<Direction, WordStatistics>
}

/**
 * A seed or an answer, and the memory that followed it. `recall_before` is null for a seed,
 * and so are `direction`, `mode` and `correct`, which say how an answer was asked.
 */
export interface HistoryEntry {
  reviewed_at: string
  grade: Grade
  is_seed: boolean
  recall_before: number | null
  stability: number
  difficulty: number
  next_review: string
  direction: Direction | null
  mode: AnswerMode | null
  correct: boolean | null
}

/** A word with its history, oldest first. */
export interface WordDetail extends Word {
  history: HistoryEntry[]
}

/** The listed words at a glance; `average_score` is null when every listed word is new. */
export interface VocabularySummary {
  total: number
  new: number
  due: number
  average_score: number | null
}

export interface WordListResponse {
  words: Word[]
  summary: VocabularySummary
}

export interface TagCount {
  tag: string
  count: number
}

export interface TagsResponse {
  tags: TagCount[]
}

/** Every word, or only those carrying `tag`, in the order they were added. */
export async function fetchWords(tag: string | null = null): Promise<WordListResponse> {
  return fetchWordList({ tags: tag === null ? [] : [tag] })
}

export type WordSort = 'score' | 'added' | 'next_review' | 'korean'
export type SortOrder = 'asc' | 'desc'

/**
 * Which words to list and in what order: those carrying any of `tags` (all of them with
 * `match: 'all'`) and none of `exclude`, sorted by `sort` in `order`. Everything left out
 * takes the backend's default: every word, in the order they were added.
 */
export interface WordListQuery {
  tags?: string[]
  match?: 'any' | 'all'
  exclude?: string[]
  sort?: WordSort
  order?: SortOrder
}

/** The words a query selects, with a summary of those words alone. */
export async function fetchWordList(query: WordListQuery): Promise<WordListResponse> {
  const params = new URLSearchParams()
  for (const tag of query.tags ?? []) {
    params.append('tag', tag)
  }
  if (query.match === 'all') {
    params.append('match', 'all')
  }
  for (const tag of query.exclude ?? []) {
    params.append('exclude', tag)
  }
  const sort = query.sort ?? 'added'
  const order = query.order ?? 'asc'
  // The default order sends nothing, so an unfiltered list is the bare route.
  if (sort !== 'added' || order !== 'asc') {
    params.append('sort', sort)
    params.append('order', order)
  }
  const search = params.toString()
  const response = await fetch('/api/vocab/words' + (search === '' ? '' : `?${search}`))
  return parseJsonOrThrow<WordListResponse>(response, 'Could not load the words.')
}

/** One word with its history. A word that does not exist rejects with a `404` `ApiError`. */
export async function fetchWord(id: number): Promise<WordDetail> {
  const response = await fetch(`/api/vocab/words/${id}`)
  return parseJsonOrThrow<WordDetail>(response, 'Could not load this word.')
}

export async function fetchTags(): Promise<TagsResponse> {
  const response = await fetch('/api/vocab/tags')
  return parseJsonOrThrow<TagsResponse>(response, 'Could not load the tags.')
}

/** What the user typed for one word: the translations exactly as typed (`house, home`). */
export interface WordFields {
  korean: string
  translations: string
  tags: string[]
}

export interface AddedWordsResponse {
  words: Word[]
}

/** One refused line of a pasted list; `line` is null for a problem no line owns. */
export interface LineError {
  line: number | null
  message: string
}

/** A pasted list refused whole: nothing was added, and every problem is listed. */
export class PasteRefusedError extends ApiError {
  readonly errors: LineError[]

  constructor(errors: LineError[]) {
    super('Nothing was added: some lines were refused.', 422)
    this.name = 'PasteRefusedError'
    this.errors = errors
  }
}

/** What adding a word at one familiarity level seeds; every figure is null for `new`. */
export interface FamiliarityLevel {
  familiarity: Familiarity
  grade: Grade | null
  score: number | null
  stability: number | null
  first_review_in_days: number | null
}

export interface FamiliarityResponse {
  levels: FamiliarityLevel[]
}

function sendJson(url: string, method: 'POST' | 'PUT', body: unknown): Promise<Response> {
  return fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function lineErrorsOf(detail: unknown): LineError[] | null {
  if (detail === null || typeof detail !== 'object') {
    return null
  }
  const errors = (detail as { errors?: unknown }).errors
  return Array.isArray(errors) ? (errors as LineError[]) : null
}

/** Adds one word. A duplicate is a `409` and an invalid entry a `422`, both `ApiError`s. */
export async function addWord(fields: WordFields & { familiarity: Familiarity }): Promise<Word> {
  const response = await sendJson('/api/vocab/words', 'POST', fields)
  return parseJsonOrThrow<Word>(response, 'Could not add the word.')
}

/**
 * Adds every word of a pasted list, or none: a refused list rejects with a
 * `PasteRefusedError` carrying each line's problem. The text is sent whole, as pasted.
 */
export async function addPastedWords(paste: {
  text: string
  tags: string[]
  familiarity: Familiarity
}): Promise<AddedWordsResponse> {
  const response = await sendJson('/api/vocab/words/batch', 'POST', paste)
  if (!response.ok) {
    const detail = detailOf(await bodyOf(response))
    const errors = lineErrorsOf(detail)
    if (errors !== null) {
      throw new PasteRefusedError(errors)
    }
    throw new ApiError(typeof detail === 'string' ? detail : 'Could not add the words.', response.status)
  }
  return (await response.json()) as AddedWordsResponse
}

/** Replaces a word's Korean, translations and tags; its familiarity cannot change. */
export async function editWord(id: number, fields: WordFields): Promise<Word> {
  const response = await sendJson(`/api/vocab/words/${id}`, 'PUT', fields)
  return parseJsonOrThrow<Word>(response, 'Could not save the word.')
}

/** Deletes a word and its whole history. */
export async function deleteWord(id: number): Promise<void> {
  const response = await fetch(`/api/vocab/words/${id}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response, 'Could not delete the word.'), response.status)
  }
}

/** What each familiarity level seeds, from `new` to `very_well`. */
export async function fetchFamiliarity(): Promise<FamiliarityResponse> {
  const response = await fetch('/api/vocab/familiarity')
  return parseJsonOrThrow<FamiliarityResponse>(response, 'Could not load the familiarity levels.')
}

// Learn and review sessions. The backend decides everything: which words, which direction and
// mode, what counts as right, what is scored. A question never carries its answer.

export type SessionKind = 'learn' | 'review'

export interface StartSessionParams {
  kind: SessionKind
  /** Omitted for every tag. */
  tag?: string
  directions: Direction[]
  /** Omitted for the backend's default. */
  size?: number
  /** A review's chosen words, in order: it takes the first `size`. Never for a learn session. */
  word_ids?: number[]
}

/** A word as the learn queue and the review picker list it. */
export interface QueuedWord {
  id: number
  korean: string
  translations: string[]
  tags: string[]
}

/** A word the review picker offers: whether it is due, and its earliest next review. */
export interface ReviewCandidate extends QueuedWord {
  due: boolean
  next_review: string
}

/** The query string naming a tag (or none) and the ticked directions, `?` included. */
function batchQuery(tag: string | null, directions: Direction[]): string {
  const query = new URLSearchParams()
  if (tag !== null) {
    query.set('tag', tag)
  }
  for (const direction of directions) {
    query.append('directions', direction)
  }
  return `?${query.toString()}`
}

/** The words a learn session can take, for `tag` and the ticked directions, in queue order. */
export async function fetchLearnQueue(tag: string | null, directions: Direction[]): Promise<QueuedWord[]> {
  const response = await fetch('/api/vocab/learn-queue' + batchQuery(tag, directions))
  const body = await parseJsonOrThrow<{ words: QueuedWord[] }>(response, 'Could not load the learn queue.')
  return body.words
}

/**
 * Moves these words to the top of the learn queue, in this order; every other word keeps
 * its order after them. Resolves to the whole queue as stored; a refusal is a `422` `ApiError`.
 */
export async function reorderLearnQueue(wordIds: number[]): Promise<QueuedWord[]> {
  const response = await sendJson('/api/vocab/learn-queue', 'PUT', { word_ids: wordIds })
  const body = await parseJsonOrThrow<{ words: QueuedWord[] }>(response, 'Could not save the new order.')
  return body.words
}

/** Every word learned in a ticked direction: the due ones first, then the others, soonest first. */
export async function fetchReviewCandidates(
  tag: string | null,
  directions: Direction[],
): Promise<ReviewCandidate[]> {
  const response = await fetch('/api/vocab/review-candidates' + batchQuery(tag, directions))
  const body = await parseJsonOrThrow<{ words: ReviewCandidate[] }>(
    response,
    'Could not load the words to review.',
  )
  return body.words
}

export interface StartSessionResponse {
  session_id: string
  kind: SessionKind
  word_count: number
  directions: Direction[]
}

/**
 * Words whose every scored question has been answered, out of the session's words, and the
 * same in scored questions. It never says which word a question is about.
 */
export interface SessionProgress {
  done: number
  total: number
  questions_done: number
  question_total: number
}

/** A new word shown openly before it is asked. */
export interface Presentation {
  type: 'presentation'
  item_id: string
  korean: string
  translations: string[]
  audio_url: string
  progress: SessionProgress
}

/**
 * A question: `prompt` is null for a voice direction, `audio_url` for a written one, and
 * `options` for typing. `scored` is false for a practice question.
 */
export interface Question {
  type: 'question'
  item_id: string
  direction: Direction
  mode: AnswerMode
  prompt: string | null
  audio_url: string | null
  options: string[] | null
  scored: boolean
  progress: SessionProgress
}

/** How a word's scored attempt went in one direction. */
export interface DirectionResult {
  direction: Direction
  correct: boolean
}

/** A word's scored attempts: `correct` only if every direction asked was right. */
export interface SummaryWord {
  korean: string
  translations: string[]
  correct: boolean
  directions: DirectionResult[]
}

export interface SessionEnd {
  type: 'end'
  summary: {
    words: SummaryWord[]
    word_count: number
    correct_count: number
    question_count: number
    correct_question_count: number
  }
}

export type SessionItem = Presentation | Question | SessionEnd

/** Exactly one of: typed text, a tapped option's index, or "I don't know". */
export type SessionAnswer = { answer: string } | { choice: number } | { dont_know: true }

/**
 * The verdict, and the word whichever way it went. The statistics are those of the direction
 * asked, null when the word was deleted meanwhile; for a practice answer, before and after
 * are the same.
 */
export interface SessionVerdict {
  correct: boolean
  korean: string
  translations: string[]
  correct_option: string | null
  scored: boolean
  statistics_before: WordStatistics | null
  statistics_after: WordStatistics | null
}

/** Starts a session; nothing to learn or review is a `409` `ApiError` saying so. */
export async function startSession(params: StartSessionParams): Promise<StartSessionResponse> {
  const response = await sendJson('/api/vocab/sessions', 'POST', params)
  return parseJsonOrThrow<StartSessionResponse>(response, 'Could not start the session.')
}

/**
 * The next item: a presentation, the pending question again, a new one, or the end. A
 * failed synthesis is a `502`, an ended session a `404`, both `ApiError`s.
 */
export async function fetchNextItem(sessionId: string): Promise<SessionItem> {
  const response = await fetch(`/api/vocab/sessions/${sessionId}/next`, { method: 'POST' })
  return parseJsonOrThrow<SessionItem>(response, 'Could not load the next question.')
}

/** Answers a question, once: a second answer is a `404` `ApiError`. */
export async function answerItem(itemId: string, answer: SessionAnswer): Promise<SessionVerdict> {
  const response = await sendJson(`/api/vocab/items/${itemId}/answer`, 'POST', answer)
  return parseJsonOrThrow<SessionVerdict>(response, 'Could not submit the answer.')
}
