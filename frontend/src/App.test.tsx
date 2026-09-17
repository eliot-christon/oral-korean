import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import App from './App'

afterEach(() => {
  vi.unstubAllGlobals()
})

test('renders the application title without making a network call', () => {
  const fetchMock = vi.fn().mockResolvedValue({
    json: () => Promise.resolve({ status: 'ok' }),
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)

  const heading = screen.getByRole('heading', { name: 'Oral Korean' })
  expect(heading.textContent).toBe('Oral Korean')
})
