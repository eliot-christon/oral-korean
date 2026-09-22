/**
 * The hash parser, as a table (vocab-words-ui T01 to T03), and the addresses `routeHref`
 * writes, read back through it. Pure: no rendering, no `window`.
 */

import { describe, expect, it } from 'vitest'

import { parseRoute, routeHref, type LinkableRoute, type Route } from './routes'

const NUMBERS: Route = { page: 'numbers' }
const WORDS: Route = { page: 'words' }
const NOT_FOUND: Route = { page: 'notFound' }

describe('parseRoute', () => {
  it.each<[string, Route]>([
    ['', NUMBERS],
    ['#', NUMBERS],
    ['#/', NUMBERS],
    ['#/numbers', NUMBERS],
    // A trailing slash is not a different page.
    ['#/numbers/', NUMBERS],
    ['#/nope', NOT_FOUND],
    ['#/numbers/extra', NOT_FOUND],
    // A hash without its leading slash is not a route of this app.
    ['#numbers', NOT_FOUND],
    // One trailing slash is forgiven, an empty segment is not.
    ['#//', NOT_FOUND],
    ['#/numbers//', NOT_FOUND],
    ['#/words', WORDS],
    ['#/words/', WORDS],
    ['#/words/12', { page: 'word', id: 12 }],
    ['#/words/12/', { page: 'word', id: 12 }],
    ['#/words/abc', NOT_FOUND],
    ['#/words/12/x', NOT_FOUND],
    // Only plain digits are an id: no zero, sign, exponent or leading zero.
    ['#/words/0', NOT_FOUND],
    ['#/words/-1', NOT_FOUND],
    ['#/words/1e3', NOT_FOUND],
    ['#/words/012', NOT_FOUND],
    // The add page, not a word with id "new".
    ['#/words/new', { page: 'addWords' }],
    ['#/words/new/', { page: 'addWords' }],
    ['#/words/new/x', NOT_FOUND],
    ['#/numbers/new', NOT_FOUND],
  ])('reads %j as %j', (hash, route) => {
    expect(parseRoute(hash)).toEqual(route)
  })
})

describe('routeHref', () => {
  it.each<LinkableRoute>([NUMBERS, WORDS, { page: 'addWords' }, { page: 'word', id: 12 }] as LinkableRoute[])(
    'writes an address that parseRoute reads back as %j',
    (route) => {
      expect(parseRoute(routeHref(route))).toEqual(route)
    },
  )

  it('writes a word address with its id', () => {
    expect(routeHref({ page: 'word', id: 12 })).toBe('#/words/12')
  })
})
