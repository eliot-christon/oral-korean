import { useState, type ReactNode } from 'react'

import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { BookIcon, KeypadIcon, ReplayIcon } from '../components/icons'
import { NavBar } from '../components/NavBar'
import { TextLink } from '../components/TextLink'

/**
 * Dev-only design preview, served by `npm run dev` at /preview.html and left out of
 * `npm run build`. It shows the tokens of `index.css` and every variant and state of the
 * primitives, so look and feel can be signed off before a real screen depends on them.
 * No backend, no fetch.
 */

// Literal class names, so Tailwind's source scan generates every swatch.
const SWATCHES: { token: string; className: string }[] = [
  { token: 'ground', className: 'bg-ground' },
  { token: 'surface', className: 'bg-surface' },
  { token: 'ink', className: 'bg-ink' },
  { token: 'muted', className: 'bg-muted' },
  { token: 'line', className: 'bg-line' },
  { token: 'primary', className: 'bg-primary' },
  { token: 'primary-strong', className: 'bg-primary-strong' },
  { token: 'primary-soft', className: 'bg-primary-soft' },
  { token: 'accent', className: 'bg-accent' },
  { token: 'accent-strong', className: 'bg-accent-strong' },
  { token: 'success', className: 'bg-success' },
  { token: 'success-soft', className: 'bg-success-soft' },
  { token: 'success-ink', className: 'bg-success-ink' },
  { token: 'error', className: 'bg-error' },
  { token: 'error-soft', className: 'bg-error-soft' },
  { token: 'error-ink', className: 'bg-error-ink' },
  { token: 'warning', className: 'bg-warning' },
  { token: 'warning-soft', className: 'bg-warning-soft' },
  { token: 'warning-ink', className: 'bg-warning-ink' },
]

const HANGUL_SAMPLES = ['영', '일곱', '스물셋', '마흔둘', '아흔아홉', '백']

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <h2 className="mb-5 text-2xl text-primary">{title}</h2>
      {children}
    </Card>
  )
}

export function Preview() {
  // Remounting the feedback list replays its entrance animations.
  const [feedbackRun, setFeedbackRun] = useState(0)

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8 sm:py-12">
      <header>
        <h1 className="text-4xl sm:text-5xl">Oral Korean</h1>
        <p className="mt-2 text-muted">
          Design preview: tokens and primitives, for sign-off. Not part of the build.
        </p>
      </header>

      <Section title="Palette">
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SWATCHES.map(({ token, className }) => (
            <li key={token} className="flex flex-col gap-1.5">
              <span className={`h-14 rounded-field border border-line/40 ${className}`} />
              <code className="text-sm text-muted">{token}</code>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Type">
        <div className="flex flex-col gap-4">
          <p className="font-display text-4xl">Display, Jua</p>
          <p className="text-lg">
            Body text, Nunito. Listen to the number, then type the digits you heard.
          </p>
          <p className="text-3xl font-bold tabular-nums">0 1 2 3 4 5 6 7 8 9 · 42 · 100</p>
          <p lang="ko" className="flex flex-wrap gap-x-5 gap-y-2 font-display text-4xl">
            {HANGUL_SAMPLES.map((word) => (
              <span key={word}>{word}</span>
            ))}
          </p>
          <p lang="ko" className="text-lg">
            마흔둘, 아흔아홉 (body size, falling through to Jua)
          </p>
        </div>
      </Section>

      <Section title="Radii and shadows">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <div className="flex h-24 items-center justify-center rounded-card bg-primary-soft text-sm">
            rounded-card
          </div>
          <div className="flex h-24 items-center justify-center rounded-field bg-primary-soft text-sm">
            rounded-field
          </div>
          <div className="flex h-24 items-center justify-center rounded-full bg-primary-soft text-sm">
            rounded-full
          </div>
          <div className="flex h-24 items-center justify-center rounded-card bg-surface text-sm shadow-soft">
            shadow-soft
          </div>
          <div className="flex h-24 items-center justify-center rounded-card bg-surface text-sm shadow-card">
            shadow-card
          </div>
          <div className="flex h-24 items-center justify-center rounded-card bg-surface text-sm shadow-glow">
            shadow-glow
          </div>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center gap-3">
            <Button>Submit</Button>
            <Button variant="secondary">Next</Button>
            <Button variant="subtle">Show answer</Button>
            <Button round aria-label="Replay">
              <ReplayIcon />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled>Submit</Button>
            <Button variant="secondary" disabled>
              Next
            </Button>
            <Button variant="subtle" disabled>
              Show answer
            </Button>
            <Button round aria-label="Replay" disabled>
              <ReplayIcon />
            </Button>
          </div>
        </div>
      </Section>

      <Section title="Fields">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Answer" type="text" inputMode="numeric" placeholder="Digits" />
          <Field label="Answer, filled" type="text" inputMode="numeric" defaultValue="42" />
          <Field label="Maximum" type="number" min={1} max={99} />
          <Field label="Maximum, filled" type="number" min={1} max={99} defaultValue={99} />
          <Field label="Numeral system" as="select" defaultValue="sino">
            <option value="sino">Sino-Korean</option>
            <option value="native">Native Korean</option>
          </Field>
          <Field label="Answer, disabled" type="text" disabled defaultValue="42" />
          <Field
            label="Words, one per line"
            as="textarea"
            lang="ko"
            className="sm:col-span-2"
            defaultValue={'사과 ; apple\n집 ; house; home'}
          />
        </div>
      </Section>

      <Section title="Navigation">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">
            The app shell pins this bar to the bottom of a phone screen, and to the top from
            sm: up. The current page has the filled pill.
          </p>
          <NavBar
            className="rounded-field border border-line/30"
            items={[
              { href: '#numbers', label: 'Numbers', icon: <KeypadIcon />, current: true },
              { href: '#words', label: 'Words', icon: <BookIcon />, current: false },
            ]}
          />
        </div>
      </Section>

      <Section title="Badges and links">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="tag">food</Badge>
            <Badge tone="tag">topik 1</Badge>
            <Badge tone="score">42%</Badge>
            <Badge tone="highlight">New</Badge>
            <Badge tone="highlight">due now</Badge>
          </div>
          <TextLink href="#words" className="self-start">
            Back to the words
          </TextLink>
        </div>
      </Section>

      <Section title="Feedback">
        <div className="flex flex-col gap-4">
          <div key={feedbackRun} className="flex flex-col gap-3">
            <Feedback tone="success">Correct!</Feedback>
            <Feedback tone="error">
              Incorrect. The answer was 42 (<span lang="ko">마흔둘</span>).
            </Feedback>
            <Feedback tone="warning">That is not a number. Type the digits you heard.</Feedback>
            <Feedback tone="neutral">
              The answer was 99 (<span lang="ko">아흔아홉</span>).
            </Feedback>
            <Feedback tone="error" role="alert">
              Could not load a question. Is the backend running?
            </Feedback>
          </div>
          <Button variant="secondary" className="self-start" onClick={() => setFeedbackRun((run) => run + 1)}>
            Replay animations
          </Button>
        </div>
      </Section>
    </main>
  )
}
