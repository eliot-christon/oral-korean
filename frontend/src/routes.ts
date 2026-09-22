import { useMemo, useSyncExternalStore } from 'react'

/**
 * The app's pages, addressed by the URL fragment (`#/numbers`), not the path: a path such as
 * `/numbers` would `404` on refresh in the built-assets run mode, where FastAPI serves
 * `frontend/dist` with no fallback to `index.html`. A hash URL still keeps the back button,
 * a link to a page and a refresh working.
 *
 * A page that takes a parameter carries it here (`{ page: 'word', id: 12 }`), so the shell's
 * `switch` over `page` is where TypeScript refuses a route without a page.
 */
export type Route =
  | { page: 'numbers' }
  | { page: 'words' }
  | { page: 'addWords' }
  | { page: 'word'; id: number }
  | { page: 'notFound' }

export type PageName = Route['page']

/** A route a link can point to: every one but `notFound`, which is no address at all. */
export type LinkableRoute = Exclude<Route, { page: 'notFound' }>

/** The landing page's address. */
export const HOME_HREF = '#/'

const NOT_FOUND: Route = { page: 'notFound' }

// Digits only: `Number('1e3')` or `Number(' 12')` would read as ids too.
const WORD_ID = /^[1-9]\d*$/

/**
 * Reads a location hash (`#/numbers`, with or without its `#`) as a route. An empty hash
 * is the landing page, and a trailing slash is not a different page; anything this app
 * has no page for, including a hash without its leading slash, is `notFound`.
 */
export function parseRoute(hash: string): Route {
  const path = hash.startsWith('#') ? hash.slice(1) : hash
  if (path === '') {
    return { page: 'numbers' }
  }
  if (!path.startsWith('/')) {
    return NOT_FOUND
  }
  const segments = path.slice(1).split('/')
  if (segments.at(-1) === '') {
    segments.pop()
  }
  if (segments.includes('')) {
    return NOT_FOUND
  }
  const [first, second] = segments
  switch (segments.length) {
    case 0:
      return { page: 'numbers' }
    case 1:
      if (first === 'numbers') {
        return { page: 'numbers' }
      }
      return first === 'words' ? { page: 'words' } : NOT_FOUND
    case 2:
      if (first !== 'words') {
        return NOT_FOUND
      }
      // `new` is the add page, never a word: ids are digits only.
      if (second === 'new') {
        return { page: 'addWords' }
      }
      return WORD_ID.test(second) ? { page: 'word', id: Number(second) } : NOT_FOUND
    default:
      return NOT_FOUND
  }
}

/** The address of a page: what `parseRoute` reads back as that same route. */
export function routeHref(route: LinkableRoute): string {
  switch (route.page) {
    case 'numbers':
      return '#/numbers'
    case 'words':
      return '#/words'
    case 'addWords':
      return '#/words/new'
    case 'word':
      return `#/words/${route.id}`
  }
}

function subscribeToHash(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

function currentHash(): string {
  return window.location.hash
}

/**
 * The current route, re-read on every `hashchange` (a link, back, forward). The same object
 * until the hash changes, so it can be an effect's dependency.
 */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribeToHash, currentHash)
  return useMemo(() => parseRoute(hash), [hash])
}
