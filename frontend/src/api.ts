/**
 * Typed wrappers around the numbers-exercise HTTP API (`src/oral_korean/api/routes/numbers.py`).
 *
 * `NumeralSystem` is a string union rather than a TypeScript `enum`: `tsconfig.app.json` sets
 * `erasableSyntaxOnly`, which rejects real `enum` declarations because they are not erasable.
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

/**
 * Reads a FastAPI error body's `detail` field, when it is a plain string (as the numbers
 * routes send for a range/synthesis failure - see `_synthesise_or_502` and
 * `InvalidRangeError` handling in `routes/numbers.py`). Falls back to `fallback` when the
 * body is not JSON or `detail` is not a string (pydantic's own validation errors send a
 * list, which is not a fact worth showing verbatim to the user of this exercise).
 */
async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string') {
      return (body as { detail: string }).detail
    }
  } catch {
    // Response body was not JSON - fall through to the generic message.
  }
  return fallback
}

async function parseJsonOrThrow<T>(response: Response, failureMessage: string): Promise<T> {
  if (!response.ok) {
    throw new Error(await errorDetail(response, failureMessage))
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
