/**
 * Helpers shared by the test files. Nothing in the app imports this module, so Vite never
 * bundles it.
 */

/**
 * Every `class="..."` attribute value found in the rendered markup, split into individual
 * tokens. Reads serialised HTML rather than `element.className` on purpose: an SVG
 * element's `className` is an `SVGAnimatedString`, not a plain string, so a uniform scan
 * over markup (which serialises `class="..."` identically for HTML and SVG elements) is
 * simpler and correct for both, and it is also what the numbers page's "never reveals"
 * scan of `container.innerHTML` already does.
 */
export function classTokensIn(container: HTMLElement): string[] {
  return [...container.innerHTML.matchAll(/class="([^"]*)"/g)].flatMap((match) =>
    match[1].split(/\s+/).filter((token) => token.length > 0),
  )
}

/** The part of a `fetch` `Response` the API wrappers read, for a stubbed `fetch` to resolve. */
export function jsonResponse(
  body: unknown,
  status = 200,
): { ok: boolean; status: number; json: () => Promise<unknown> } {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) }
}

/** The statistics of a word never reviewed, as the backend sends them: nothing known. */
export const NEW_WORD_STATISTICS = {
  score: null,
  recall: null,
  stability: null,
  difficulty: null,
  phase: 'new',
  next_review: null,
  last_review: null,
  due: false,
  review_count: 0,
  lapse_count: 0,
}

/**
 * A word shaped like the vocabulary routes' `WordResponse`: new, untagged, added
 * 2026-09-22, unless `overrides` says otherwise.
 */
export function wordStub(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    korean: '사과',
    translations: ['apple'],
    tags: [],
    familiarity: 'new',
    added_at: '2026-09-22T10:00:00Z',
    statistics: NEW_WORD_STATISTICS,
    ...overrides,
  }
}
