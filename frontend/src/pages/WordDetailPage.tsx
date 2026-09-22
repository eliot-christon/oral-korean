import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import {
  ApiError,
  deleteWord,
  editWord,
  errorMessage,
  fetchWord,
  type HistoryEntry,
  type Word,
  type WordDetail,
  type WordStatistics,
} from '../api'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { TextLink } from '../components/TextLink'
import {
  familiarityLabel,
  formatDateTime,
  formatDays,
  formatDifficulty,
  formatPercent,
  formatScore,
  formatTimeUntil,
  gradeLabel,
  tagsFromField,
  tagsToField,
} from '../format'
import { isSubmitEnter, KOREAN_INPUT } from '../koreanInput'
import { leaveNotice } from '../notice'
import { routeHref } from '../routes'
import { PageLayout } from './PageLayout'

const WORDS_HREF = routeHref({ page: 'words' })

interface Statistic {
  label: string
  value: ReactNode
  explanation: string
}

/**
 * Every figure FSRS keeps, each with one line in plain words. A new word has no memory yet,
 * so it shows its score as "New" and none of the figures that only a review gives.
 */
function statisticsOf(word: WordDetail, now: Date): Statistic[] {
  const figures: WordStatistics = word.statistics
  const rows: Statistic[] = [
    {
      label: 'Score',
      value: formatScore(figures.score),
      explanation:
        'Strength: rises when you get it right, drops when you miss, 100% once it lasts a year.',
    },
  ]
  if (figures.recall !== null) {
    rows.push({
      label: 'Recall',
      value: formatPercent(figures.recall),
      explanation:
        'Predicted chance you recall it right now. It reads 100% for a day after any review, ' +
        'a missed one included: FSRS counts whole days since the last one.',
    })
  }
  if (figures.stability !== null) {
    rows.push({
      label: 'Stability',
      value: formatDays(figures.stability),
      explanation: 'Days until that chance falls to 90%.',
    })
  }
  if (figures.difficulty !== null) {
    rows.push({
      label: 'Difficulty',
      value: formatDifficulty(figures.difficulty),
      explanation: 'How hard the word is for you: the higher, the more slowly its strength grows.',
    })
  }
  if (figures.next_review !== null) {
    rows.push({
      label: 'Next review',
      value: (
        <>
          {formatDateTime(figures.next_review)}{' '}
          <span className="font-semibold text-muted">
            ({figures.due ? 'due now' : formatTimeUntil(figures.next_review, now)})
          </span>
        </>
      ),
      explanation: 'When it is due to be asked again.',
    })
  }
  if (figures.last_review !== null) {
    rows.push({
      label: 'Last review',
      value: formatDateTime(figures.last_review),
      explanation: 'Your last answer, or when you added it as a word you already knew.',
    })
  }
  rows.push(
    {
      label: 'Reviews',
      value: String(figures.review_count),
      explanation: 'Answers counted. Adding a word you already know does not count as one.',
    },
    {
      label: 'Lapses',
      value: String(figures.lapse_count),
      explanation: 'Times you missed it after you had learned it.',
    },
    {
      label: 'Added on',
      value: formatDateTime(word.added_at),
      explanation: 'When it entered your vocabulary.',
    },
    {
      label: 'Added as',
      value: familiarityLabel(word.familiarity),
      explanation: 'How well you said you knew it when you added it.',
    },
  )
  return rows
}

function StatisticsList({ rows }: { rows: Statistic[] }) {
  return (
    <dl className="flex flex-col divide-y divide-line/20">
      {rows.map(({ label, value, explanation }) => (
        <div key={label} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
          <dt className="min-w-0">
            <span className="font-bold">{label}</span>
            <span className="block text-sm text-muted">{explanation}</span>
          </dt>
          <dd className="shrink-0 text-right font-bold text-primary">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function whatHappened(entry: HistoryEntry, word: WordDetail): string {
  if (entry.is_seed) {
    return (
      `Added as '${familiarityLabel(word.familiarity)}' - counted as a first review ` +
      `graded ${gradeLabel(entry.grade)}`
    )
  }
  return 'Answered'
}

function HistoryItem({ entry, word }: { entry: HistoryEntry; word: WordDetail }) {
  const figures: [string, string][] = [
    // A seed had no memory before it, so no recall to predict.
    ['Recall before', entry.recall_before === null ? '-' : formatPercent(entry.recall_before)],
    ['Stability after', formatDays(entry.stability)],
    ['Next review after', formatDateTime(entry.next_review)],
  ]
  return (
    <li className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-bold text-muted">{formatDateTime(entry.reviewed_at)}</span>
        <Badge tone={entry.is_seed ? 'tag' : 'score'}>{gradeLabel(entry.grade)}</Badge>
      </div>
      <p className="font-semibold">{whatHappened(entry, word)}</p>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        {figures.map(([label, value]) => (
          <div key={label} className="flex flex-col-reverse">
            <dt className="text-muted">{label}</dt>
            <dd className="font-bold">{value}</dd>
          </div>
        ))}
      </dl>
    </li>
  )
}

function WordNotFound() {
  return (
    <PageLayout>
      <Card className="flex flex-col items-center gap-4 text-center">
        <h1 className="text-3xl text-primary sm:text-4xl">Word not found</h1>
        <p className="text-muted">No word has this address. It may have been deleted.</p>
        <TextLink href={WORDS_HREF} className="self-center">
          Back to the words
        </TextLink>
      </Card>
    </PageLayout>
  )
}

/**
 * Korean, translations and tags, editable; the familiarity level shown with why it is not.
 * A refused save keeps the form open with what the user typed.
 */
function EditWordForm({
  word,
  onSaved,
  onCancel,
}: {
  word: Word
  onSaved: (saved: Word) => void
  onCancel: () => void
}) {
  const [korean, setKorean] = useState(word.korean)
  // Back in the form they are typed in, and sent back as typed.
  const [translations, setTranslations] = useState(word.translations.join('; '))
  const [tags, setTags] = useState(tagsToField(word.tags))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const inFlight = useRef(false)
  const koreanRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    koreanRef.current?.focus()
  }, [])

  const ready = korean.trim() !== '' && translations.trim() !== ''

  async function save(): Promise<void> {
    if (!ready || inFlight.current) {
      return
    }
    inFlight.current = true
    setSaving(true)
    setError(null)
    try {
      onSaved(await editWord(word.id, { korean, translations, tags: tagsFromField(tags) }))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      inFlight.current = false
      setSaving(false)
    }
  }

  function saveOnEnter(event: KeyboardEvent): void {
    if (isSubmitEnter(event)) {
      event.preventDefault()
      void save()
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <h2 className="text-2xl text-primary">Edit</h2>
      <Field
        ref={koreanRef}
        label="Korean"
        type="text"
        {...KOREAN_INPUT}
        enterKeyHint="done"
        value={korean}
        onChange={(event) => setKorean(event.target.value)}
        onKeyDown={saveOnEnter}
      />
      <Field
        label="Translations"
        type="text"
        autoComplete="off"
        enterKeyHint="done"
        value={translations}
        onChange={(event) => setTranslations(event.target.value)}
        onKeyDown={saveOnEnter}
      />
      <Field
        label="Tags, separated by commas"
        type="text"
        autoCapitalize="off"
        autoComplete="off"
        enterKeyHint="done"
        value={tags}
        onChange={(event) => setTags(event.target.value)}
        onKeyDown={saveOnEnter}
      />
      <p className="text-sm text-muted">
        Added as <strong className="text-ink">{familiarityLabel(word.familiarity)}</strong>. That
        cannot change: the word's memory has moved on since it was added.
      </p>
      {error !== null && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="subtle" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={() => void save()} disabled={!ready || saving}>
          Save
        </Button>
      </div>
    </Card>
  )
}

/**
 * Deleting takes two steps, on the page itself (not `window.confirm`, which tests and
 * phones handle badly): the word's whole history goes with it, and there is no undo.
 */
function DeleteWord({ word }: { word: Word }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const keepRef = useRef<HTMLButtonElement>(null)

  // The safe choice has focus when the question appears.
  useEffect(() => {
    if (confirming) {
      keepRef.current?.focus()
    }
  }, [confirming])

  async function confirmDelete(): Promise<void> {
    setDeleting(true)
    setError(null)
    try {
      await deleteWord(word.id)
      leaveNotice('Deleted one word, with its history.')
      window.location.hash = WORDS_HREF
    } catch (err) {
      setError(errorMessage(err))
      setDeleting(false)
    }
  }

  if (!confirming) {
    return (
      <Button variant="subtle" className="self-start" onClick={() => setConfirming(true)}>
        Delete word
      </Button>
    )
  }
  return (
    <Card role="group" aria-label="Delete this word?" className="flex basis-full flex-col gap-4">
      <p className="font-semibold">
        Delete <span lang="ko">{word.korean}</span> and its whole history? This cannot be
        undone.
      </p>
      {error !== null && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button ref={keepRef} variant="subtle" onClick={() => setConfirming(false)} disabled={deleting}>
          Keep it
        </Button>
        <Button onClick={() => void confirmDelete()} disabled={deleting}>
          Delete for good
        </Button>
      </div>
    </Card>
  )
}

/** One word: everything FSRS knows about it, explained, and its history, oldest first. */
export function WordDetailPage({ id }: { id: number }) {
  const [word, setWord] = useState<WordDetail | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)

  function handleSaved(current: WordDetail, updated: Word): void {
    // An edit keeps the word's memory and history, and the answer carries no history.
    setWord({ ...updated, history: current.history })
    setEditing(false)
    setSaved(true)
  }

  useEffect(() => {
    let cancelled = false
    fetchWord(id)
      .then((response) => {
        if (!cancelled) {
          setWord(response)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return
        }
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true)
        } else {
          setError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [id])

  if (notFound) {
    return <WordNotFound />
  }

  return (
    <PageLayout>
      <TextLink href={WORDS_HREF} className="-ml-4 self-start">
        All words
      </TextLink>
      {error !== null && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {word === null ? (
        error === null && <p className="text-center text-muted">Loading the word...</p>
      ) : (
        <>
          <header className="flex flex-col gap-2">
            <h1 lang="ko" className="text-5xl wrap-break-word text-primary">
              {word.korean}
            </h1>
            <p className="text-lg">{word.translations.join('; ')}</p>
            {word.tags.length > 0 && (
              <p className="flex flex-wrap gap-2">
                {word.tags.map((tag) => (
                  <Badge key={tag} tone="tag">
                    {tag}
                  </Badge>
                ))}
              </p>
            )}
          </header>

          {saved && <Feedback tone="success">Saved.</Feedback>}
          {editing ? (
            <EditWordForm
              word={word}
              onSaved={(updated) => handleSaved(word, updated)}
              onCancel={() => setEditing(false)}
            />
          ) : (
            <div className="flex flex-wrap items-start gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setSaved(false)
                  setEditing(true)
                }}
              >
                Edit
              </Button>
              <DeleteWord word={word} />
            </div>
          )}

          <Card className="flex flex-col gap-4">
            <h2 className="text-2xl text-primary">Statistics</h2>
            <StatisticsList rows={statisticsOf(word, new Date())} />
          </Card>

          <Card className="flex flex-col gap-4">
            <h2 className="text-2xl text-primary">History</h2>
            {word.history.length === 0 ? (
              <p className="text-muted">No reviews yet.</p>
            ) : (
              <ol className="flex flex-col divide-y divide-line/20">
                {word.history.map((entry, index) => (
                  // In order and never reordered, so the position is a stable key.
                  <HistoryItem key={index} entry={entry} word={word} />
                ))}
              </ol>
            )}
          </Card>
        </>
      )}
    </PageLayout>
  )
}
