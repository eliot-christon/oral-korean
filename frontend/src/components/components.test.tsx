/**
 * Tests for the four design-foundation primitives, against
 * `.claude/work/ui-redesign/tickets/T02-design-foundation.md`'s "Test contract". None of
 * `Button`, `Card`, `Field` or `Feedback` exist yet; this file is written against the API
 * settled before the code (named exports, React 19, `ref` as an ordinary prop - no
 * `forwardRef`):
 *
 *   function Button(props: ComponentProps<'button'> & {
 *     variant?: 'primary' | 'secondary' | 'subtle'   // default 'primary'
 *     round?: boolean                                 // large round icon-only form
 *   }): JSX.Element
 *
 *   function Card(props: ComponentProps<'div'>): JSX.Element
 *
 *   type FieldProps =
 *     | ({ label: ReactNode; as?: 'input' } & ComponentProps<'input'>)
 *     | ({ label: ReactNode; as: 'select' } & ComponentProps<'select'>)
 *   function Field(props: FieldProps): JSX.Element
 *
 *   type FeedbackTone = 'success' | 'error' | 'warning' | 'neutral'
 *   function Feedback(props: {
 *     tone: FeedbackTone
 *     role?: 'status' | 'alert'   // default 'status'
 *     children: ReactNode
 *   }): JSX.Element
 *
 *   function ReplayIcon(): JSX.Element   // frontend/src/components/icons.tsx, inline <svg aria-hidden="true">
 *
 * `NavBar` joined them with the app shell (vocab-words-ui T01), and `Badge` and `TextLink`
 * with the word pages (T02), tested below the same way.
 *
 * Same conventions as `pages/NumbersPage.test.tsx`: `cleanup()` is called explicitly in
 * `afterEach` (Testing Library's auto-cleanup never registers here because
 * `vite.config.ts` does not set `test.globals`), no `@testing-library/jest-dom` matcher is
 * used (every assertion reads a plain DOM property), and nothing touches the network -
 * these primitives have no reason to call `fetch` at all.
 *
 * Judgment calls this file makes, because the ticket's test contract names one behaviour
 * per case rather than markup, and two things beyond the contract's own list:
 *   - `Card` has no dedicated bullet in the ticket's test contract (only `Button`, `Field`
 *     and `Feedback` do), but the ticket's own cross-primitive rule - "wrap the native
 *     element and pass native props through" - applies to it too, so one test below holds
 *     `Card` to that rule via a `role`/`aria-label` pair, the same way the numbers page
 *     will need it to (an exercise panel with a heading naming it).
 *   - the "motion is opt-in" test additionally asserts that at least one `animate-` class
 *     token is found at all, not merely that every one found starts with `motion-safe:`
 *     (which would pass vacuously if the implementation wired no motion in yet). This
 *     assumes at least one primitive - `Feedback`, the component that carries the verdict
 *     moments the epic's "Motion" section names (a pop, a shake, a slide-in) - bakes its
 *     `--animate-*` token into its own markup rather than deferring all motion to T03's
 *     integration into `App.tsx` (which this ticket does not touch). If the real
 *     implementation defers every animation class to T03, this one assertion needs
 *     dropping; the "every token starts with motion-safe:" half of the test still holds
 *     either way.
 */

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { classTokensIn } from '../testUtils'
import { Badge, type BadgeTone } from './Badge'
import { Button } from './Button'
import { Card } from './Card'
import { Feedback, type FeedbackTone } from './Feedback'
import { Field } from './Field'
import { KeypadIcon, ReplayIcon } from './icons'
import { NavBar, type NavItem } from './NavBar'
import { TextLink } from './TextLink'

afterEach(() => {
  cleanup()
})

describe('Button', () => {
  it('is a native button named by its content', () => {
    render(<Button>Submit</Button>)

    const button = screen.getByRole('button', { name: 'Submit' })
    expect(button.tagName).toBe('BUTTON')
  })

  it('defaults to type="button" so it is never a submit button by accident', () => {
    render(<Button>Click me</Button>)

    const button = screen.getByRole('button', { name: 'Click me' })
    expect(button.getAttribute('type')).toBe('button')
  })

  it('blocks clicks while disabled', () => {
    const handleClick = vi.fn()
    render(
      <Button disabled onClick={handleClick}>
        Click me
      </Button>,
    )

    const button = screen.getByRole('button', { name: 'Click me' }) as HTMLButtonElement
    fireEvent.click(button)

    expect(handleClick).not.toHaveBeenCalled()
    expect(button.disabled).toBe(true)
  })

  it('calls onClick exactly once per click while enabled', () => {
    const handleClick = vi.fn()
    render(<Button onClick={handleClick}>Click me</Button>)

    fireEvent.click(screen.getByRole('button', { name: 'Click me' }))

    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('keeps its accessible name from aria-label on the round icon-only form, with a decorative icon', () => {
    const { container } = render(
      <Button round aria-label="Replay">
        <ReplayIcon />
      </Button>,
    )

    const button = screen.getByRole('button', { name: 'Replay' })
    const icons = container.querySelectorAll('svg')
    expect(icons.length).toBeGreaterThan(0)
    icons.forEach((icon) => {
      expect(icon.getAttribute('aria-hidden')).toBe('true')
      expect(button.contains(icon)).toBe(true)
    })
  })
})

describe('Card', () => {
  it('wraps a native div and passes native props through', () => {
    render(
      <Card role="region" aria-label="Exercise panel">
        Exercise content
      </Card>,
    )

    const card = screen.getByRole('region', { name: 'Exercise panel' })
    expect(card.tagName).toBe('DIV')
    expect(card.textContent).toBe('Exercise content')
  })
})

describe('Field', () => {
  it('labels a text input, found by the textbox role', () => {
    render(<Field label="Answer" type="text" />)

    const input = screen.getByRole('textbox', { name: 'Answer' })
    expect(input.tagName).toBe('INPUT')
  })

  it('labels a number input and passes its bounds through', () => {
    render(<Field label="Maximum" type="number" min={1} max={99} />)

    const input = screen.getByRole('spinbutton', { name: 'Maximum' }) as HTMLInputElement
    expect(input.min).toBe('1')
    expect(input.max).toBe('99')
  })

  it('labels a select and renders both of its options', () => {
    render(
      <Field label="Numeral system" as="select">
        <option value="sino">Sino-Korean</option>
        <option value="native">Native Korean</option>
      </Field>,
    )

    const select = screen.getByRole('combobox', { name: 'Numeral system' })
    expect(select.tagName).toBe('SELECT')
    expect(within(select).getByRole('option', { name: 'Sino-Korean' })).toBeDefined()
    expect(within(select).getByRole('option', { name: 'Native Korean' })).toBeDefined()
  })

  it('passes arbitrary input attributes through untouched', () => {
    render(<Field label="Answer" type="text" inputMode="numeric" />)

    const input = screen.getByRole('textbox', { name: 'Answer' })
    expect(input.getAttribute('type')).toBe('text')
    expect(input.getAttribute('inputmode')).toBe('numeric')
  })

  it('labels a textarea and passes its attributes through', () => {
    render(<Field label="Words, one per line" as="textarea" lang="ko" rows={6} />)

    const textarea = screen.getByRole('textbox', { name: 'Words, one per line' })
    expect(textarea.tagName).toBe('TEXTAREA')
    expect(textarea.getAttribute('lang')).toBe('ko')
    expect(textarea.getAttribute('rows')).toBe('6')
  })

  it('forwards onChange to the caller with the typed value', () => {
    const handleChange = vi.fn()
    render(<Field label="Answer" type="text" onChange={handleChange} />)

    const input = screen.getByRole('textbox', { name: 'Answer' })
    fireEvent.change(input, { target: { value: '7' } })

    expect(handleChange).toHaveBeenCalledTimes(1)
    const event = handleChange.mock.calls[0][0] as { target: { value: string } }
    expect(event.target.value).toBe('7')
  })
})

describe('Feedback', () => {
  const TONES: FeedbackTone[] = ['success', 'error', 'warning', 'neutral']
  const MESSAGE = 'Incorrect. The answer was 42 (마흔둘).'

  it.each(TONES)('renders exactly the callers message for the %s tone, with no added words', (tone) => {
    render(<Feedback tone={tone}>{MESSAGE}</Feedback>)

    const status = screen.getByRole('status')
    expect(status.textContent).toBe(MESSAGE)
  })

  it('renders as an alert instead of a status when asked', () => {
    render(
      <Feedback tone="error" role="alert">
        Could not reach the backend. Is it running?
      </Feedback>,
    )

    expect(screen.getByRole('alert')).toBeDefined()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('names its tone in data-tone, for tests that cannot see colour', () => {
    TONES.forEach((tone) => {
      render(<Feedback tone={tone}>Message</Feedback>)
      expect(screen.getByRole('status').dataset.tone).toBe(tone)
      cleanup()
    })
  })

  it('marks its icon as decorative for every tone', () => {
    TONES.forEach((tone) => {
      const { container } = render(<Feedback tone={tone}>Message</Feedback>)
      const icons = container.querySelectorAll('svg')
      expect(icons.length).toBeGreaterThan(0)
      icons.forEach((icon) => expect(icon.getAttribute('aria-hidden')).toBe('true'))
    })
  })

  it('gives every tone a different icon, since colour is never the only signal', () => {
    const iconMarkupByTone = new Map<FeedbackTone, string>()

    TONES.forEach((tone) => {
      const { container } = render(<Feedback tone={tone}>Message</Feedback>)
      const icon = container.querySelector('svg')
      if (icon === null) {
        throw new Error(`Feedback tone=${tone} rendered no icon`)
      }
      iconMarkupByTone.set(tone, icon.outerHTML)
    })

    for (let i = 0; i < TONES.length; i += 1) {
      for (let j = i + 1; j < TONES.length; j += 1) {
        expect(iconMarkupByTone.get(TONES[i])).not.toBe(iconMarkupByTone.get(TONES[j]))
      }
    }
  })
})

describe('NavBar', () => {
  const ITEMS: NavItem[] = [
    { href: '#/numbers', label: 'Numbers', icon: <KeypadIcon />, current: true },
    { href: '#/words', label: 'Words', icon: <KeypadIcon />, current: false },
  ]

  it('is a navigation landmark with one native link per item, named by its label', () => {
    render(<NavBar items={ITEMS} />)

    const navigation = screen.getByRole('navigation')
    const links = within(navigation).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Numbers', 'Words'])
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['#/numbers', '#/words'])
    links.forEach((link) => expect(link.tagName).toBe('A'))
  })

  it('marks the current item, and only that one, with aria-current="page"', () => {
    render(<NavBar items={ITEMS} />)

    expect(screen.getByRole('link', { name: 'Numbers' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Words' }).getAttribute('aria-current')).toBeNull()
  })

  it('keeps its icons decorative, so each link is named by its label alone', () => {
    const { container } = render(<NavBar items={ITEMS} />)

    const icons = container.querySelectorAll('svg')
    expect(icons.length).toBe(ITEMS.length)
    icons.forEach((icon) => expect(icon.getAttribute('aria-hidden')).toBe('true'))
  })
})

describe('Badge', () => {
  const TONES: BadgeTone[] = ['tag', 'score', 'highlight']

  it.each(TONES)('renders exactly its words for the %s tone, and names the tone for tests', (tone) => {
    const { container } = render(<Badge tone={tone}>due now</Badge>)

    const badge = container.firstElementChild as HTMLElement
    expect(badge.tagName).toBe('SPAN')
    expect(badge.textContent).toBe('due now')
    expect(badge.dataset.tone).toBe(tone)
  })
})

describe('TextLink', () => {
  it('is a native link named by its content, passing its props through', () => {
    render(
      <TextLink href="#/words" aria-describedby="hint">
        Back to the words
      </TextLink>,
    )

    const link = screen.getByRole('link', { name: 'Back to the words' })
    expect(link.tagName).toBe('A')
    expect(link.getAttribute('href')).toBe('#/words')
    expect(link.getAttribute('aria-describedby')).toBe('hint')
  })
})

describe('Across all primitives', () => {
  it('applies every animation only through the motion-safe: variant', () => {
    const { container } = render(
      <>
        <Button>Primary</Button>
        <Button disabled>Primary disabled</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="subtle">Subtle</Button>
        <Button round aria-label="Replay">
          <ReplayIcon />
        </Button>
        <Card>Card content</Card>
        <Field label="Answer" type="text" />
        <Field label="Maximum" type="number" min={1} max={99} />
        <Field label="Numeral system" as="select">
          <option value="sino">Sino-Korean</option>
          <option value="native">Native Korean</option>
        </Field>
        <Field label="Words, one per line" as="textarea" />
        <Feedback tone="success">Correct!</Feedback>
        <Feedback tone="error">Incorrect. The answer was 42 (마흔둘).</Feedback>
        <Feedback tone="warning">That is not a number. Type the digits you heard.</Feedback>
        <Feedback tone="neutral" role="alert">
          Could not reach the backend. Is it running?
        </Feedback>
        <NavBar items={[{ href: '#/numbers', label: 'Numbers', icon: <KeypadIcon />, current: true }]} />
        <Badge tone="score">42%</Badge>
        <TextLink href="#/words">Back to the words</TextLink>
      </>,
    )

    const animationTokens = classTokensIn(container).filter((token) => token.includes('animate-'))

    // Not merely vacuously true: see this file's header comment for the assumption this rests on.
    expect(animationTokens.length).toBeGreaterThan(0)
    animationTokens.forEach((token) => {
      expect(token.startsWith('motion-safe:')).toBe(true)
    })
  })
})
