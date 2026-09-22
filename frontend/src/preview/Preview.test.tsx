/**
 * Test for the T02 dev-only preview page, against
 * `.claude/work/ui-redesign/tickets/T02-design-foundation.md`'s "Test contract": "the
 * preview renders". `Preview` does not exist yet; this file is written against the settled
 * API:
 *
 *   function Preview(): JSX.Element   // frontend/src/preview/Preview.tsx
 *
 * mounted by `frontend/src/preview/main.tsx` into `frontend/preview.html` - neither of
 * which this test imports, since Vite's own dev server and build are what actually serve
 * that HTML file; a component test can only render the React tree.
 *
 * This is a rot guard, not a design review: it does not assert anything about colour,
 * spacing or the token names in `frontend/src/index.css` (vitest replaces every CSS import
 * with an empty string and jsdom has no layout, so none of that is observable here - see
 * `epic.md`). It only keeps the preview page from silently losing a control as the
 * primitives change underneath it.
 *
 * Same conventions as `pages/NumbersPage.test.tsx`: `cleanup()` is called explicitly in
 * `afterEach` (Testing Library's auto-cleanup never registers without `test.globals`), no
 * `@testing-library/jest-dom` matcher is used (every assertion reads a plain DOM
 * property).
 *
 * `fetch` is stubbed to reject and asserted never called: the ticket requires the preview
 * page to need "no backend, no fetch, no /api/ literal anywhere in it", and a rejecting
 * stub turns "never calls fetch" from an assumption into something this test actually
 * checks, the same way every other fetch-touching test in this project stubs the network
 * rather than trusting the component not to reach for it.
 */

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Preview } from './Preview'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Preview', () => {
  it('renders every control the numbers page will reuse, with no network', () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error('Preview must not call fetch')))
    vi.stubGlobal('fetch', fetchSpy)

    const { container } = render(<Preview />)

    expect(screen.getAllByRole('heading').length).toBeGreaterThan(0)

    const buttons = screen.getAllByRole('button') as HTMLButtonElement[]
    expect(buttons.length).toBeGreaterThan(0)
    expect(buttons.some((button) => !button.disabled)).toBe(true)
    expect(buttons.some((button) => button.disabled)).toBe(true)

    expect(screen.getAllByRole('textbox').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('spinbutton').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('combobox').length).toBeGreaterThan(0)

    // The native-Korean reading of 42, one of the ticket's named Hangul samples (영, 일곱,
    // 스물셋, 마흔둘, 아흔아홉, 백) - read from the ticket, not from any implementation output.
    expect(container.textContent).toContain('마흔둘')

    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
