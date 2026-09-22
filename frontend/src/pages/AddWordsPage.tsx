import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import {
  addPastedWords,
  addWord,
  errorMessage,
  fetchFamiliarity,
  PasteRefusedError,
  type Familiarity,
  type FamiliarityLevel,
  type LineError,
} from '../api'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { TextLink } from '../components/TextLink'
import { familiarityOption, tagsFromField } from '../format'
import { isSubmitEnter, KOREAN_INPUT } from '../koreanInput'
import { leaveNotice } from '../notice'
import { routeHref } from '../routes'
import { PageLayout } from './PageLayout'

type Mode = 'one' | 'paste'

const MODES: [Mode, string][] = [
  ['one', 'One word'],
  ['paste', 'Paste a list'],
]

function LineErrors({ errors }: { errors: LineError[] }) {
  return (
    <Feedback tone="error" role="alert">
      <p>Nothing was added. Fix these lines, then add the list again:</p>
      <ul className="mt-2 flex flex-col gap-1">
        {errors.map((error, index) => (
          // A refusal lists each problem once, in line order: the position is a stable key.
          <li key={index}>
            {error.line === null ? error.message : `Line ${error.line}: ${error.message}`}
          </li>
        ))}
      </ul>
    </Feedback>
  )
}

/**
 * Adds words, one at a time or as a pasted list, with tags and a familiarity level for all
 * of them. Every rule lives in the backend: this page sends what was typed, as typed, and
 * shows what the backend answers.
 */
export function AddWordsPage() {
  const [mode, setMode] = useState<Mode>('one')
  const [levels, setLevels] = useState<FamiliarityLevel[] | null>(null)
  const [levelsError, setLevelsError] = useState<string | null>(null)

  const [korean, setKorean] = useState('')
  const [translations, setTranslations] = useState('')
  const [text, setText] = useState('')
  // Kept from one word to the next: a series of words often shares them.
  const [tags, setTags] = useState('')
  const [familiarity, setFamiliarity] = useState<Familiarity>('new')

  const [added, setAdded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lineErrors, setLineErrors] = useState<LineError[] | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // State alone lets a second click in before the first one re-renders the button disabled.
  const inFlight = useRef(false)
  const koreanRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    fetchFamiliarity()
      .then((response) => {
        if (!cancelled) {
          setLevels(response.levels)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLevelsError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const ready =
    mode === 'one' ? korean.trim() !== '' && translations.trim() !== '' : text.trim() !== ''

  function chooseMode(next: Mode): void {
    setMode(next)
    setAdded(null)
    setError(null)
    setLineErrors(null)
  }

  async function addOne(): Promise<void> {
    try {
      const word = await addWord({ korean, translations, tags: tagsFromField(tags), familiarity })
      setKorean('')
      setTranslations('')
      setAdded(word.korean)
      koreanRef.current?.focus()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function addList(): Promise<void> {
    try {
      const response = await addPastedWords({ text, tags: tagsFromField(tags), familiarity })
      const count = response.words.length
      leaveNotice(`Added ${count} ${count === 1 ? 'word' : 'words'}.`)
      window.location.hash = routeHref({ page: 'words' })
    } catch (err) {
      if (err instanceof PasteRefusedError) {
        setLineErrors(err.errors)
      } else {
        setError(errorMessage(err))
      }
    }
  }

  async function submit(): Promise<void> {
    if (!ready || inFlight.current) {
      return
    }
    inFlight.current = true
    setSubmitting(true)
    setAdded(null)
    setError(null)
    setLineErrors(null)
    try {
      await (mode === 'one' ? addOne() : addList())
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  function submitOnEnter(event: KeyboardEvent): void {
    if (isSubmitEnter(event)) {
      event.preventDefault()
      void submit()
    }
  }

  return (
    <PageLayout>
      <TextLink href={routeHref({ page: 'words' })} className="-ml-4 self-start">
        All words
      </TextLink>
      <header>
        <h1 className="text-4xl text-primary sm:text-5xl">Add words</h1>
        <p className="mt-1 text-muted">One at a time, or a whole list at once.</p>
      </header>

      <div role="group" aria-label="How to add" className="flex flex-wrap gap-2">
        {MODES.map(([value, label]) => (
          <Button
            key={value}
            variant={mode === value ? 'secondary' : 'subtle'}
            aria-pressed={mode === value}
            onClick={() => chooseMode(value)}
          >
            {label}
          </Button>
        ))}
      </div>

      {levelsError !== null && (
        <Feedback tone="error" role="alert">
          {levelsError}
        </Feedback>
      )}

      <Card className="flex flex-col gap-4">
        {mode === 'one' ? (
          <>
            <Field
              ref={koreanRef}
              label="Korean"
              type="text"
              {...KOREAN_INPUT}
              enterKeyHint="done"
              value={korean}
              onChange={(event) => setKorean(event.target.value)}
              onKeyDown={submitOnEnter}
            />
            <Field
              label="Translations"
              type="text"
              placeholder="house; home"
              autoComplete="off"
              enterKeyHint="done"
              value={translations}
              onChange={(event) => setTranslations(event.target.value)}
              onKeyDown={submitOnEnter}
            />
          </>
        ) : (
          <Field
            as="textarea"
            label="Words, one per line: the Korean, a semicolon, then its translations"
            placeholder={'사과 ; apple\n집 ; house; home'}
            {...KOREAN_INPUT}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        )}

        <Field
          label={mode === 'one' ? 'Tags, separated by commas' : 'Tags for every word, separated by commas'}
          type="text"
          placeholder="food, topik 1"
          autoCapitalize="off"
          autoComplete="off"
          enterKeyHint="done"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          onKeyDown={submitOnEnter}
        />

        {levels !== null && (
          <Field
            label={mode === 'one' ? 'How well you know it' : 'How well you know them'}
            as="select"
            value={familiarity}
            onChange={(event) => setFamiliarity(event.target.value as Familiarity)}
          >
            {levels.map((level) => (
              <option key={level.familiarity} value={level.familiarity}>
                {familiarityOption(level)}
              </option>
            ))}
          </Field>
        )}

        {error !== null && (
          <Feedback tone="error" role="alert">
            {error}
          </Feedback>
        )}
        {lineErrors !== null && <LineErrors errors={lineErrors} />}
        {added !== null && (
          <Feedback tone="success">
            Added <span lang="ko">{added}</span>.
          </Feedback>
        )}

        <Button className="self-end" onClick={() => void submit()} disabled={!ready || submitting}>
          {mode === 'one' ? 'Add word' : 'Add the list'}
        </Button>
      </Card>
    </PageLayout>
  )
}
