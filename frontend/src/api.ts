/**
 * Typed wrappers around the backend's HTTP API: the numbers exercise
 * (`src/oral_korean/api/routes/numbers.py`) and the vocabulary
 * (`src/oral_korean/api/routes/vocab_words.py`).
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
  statistics: WordStatistics
}

/** A seed or an answer, and the memory that followed it. `recall_before` is null for a seed. */
export interface HistoryEntry {
  reviewed_at: string
  grade: Grade
  is_seed: boolean
  recall_before: number | null
  stability: number
  difficulty: number
  next_review: string
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
  const query = tag === null ? '' : `?${new URLSearchParams({ tag }).toString()}`
  const response = await fetch('/api/vocab/words' + query)
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

/** What the user typed for one word: the translations exactly as typed (`house; home`). */
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
