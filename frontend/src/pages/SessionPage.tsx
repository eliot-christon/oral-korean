import { useEffect, useEffectEvent, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import {
  ApiError,
  answerItem,
  errorMessage,
  fetchNextItem,
  fetchTags,
  fetchWords,
  startSession,
  type Direction,
  type Presentation,
  type Question,
  type SessionAnswer,
  type SessionEnd,
  type SessionKind,
  type SessionVerdict,
  type StartSessionParams,
  type TagCount,
  type WordStatistics,
} from '../api'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { CheckIcon, ReplayIcon } from '../components/icons'
import { TextLink } from '../components/TextLink'
import { directionLabel, formatDays, formatDue, formatScore } from '../format'
import { isSubmitEnter, KOREAN_INPUT } from '../koreanInput'
import { routeHref } from '../routes'
import { PageLayout } from './PageLayout'

const DIRECTIONS: Direction[] = [
  'hangul_to_translation',
  'translation_to_hangul',
  'voice_to_hangul',
  'voice_to_translation',
]

// A record, so a direction added to the union without its words here fails to compile.
const DIRECTION_INSTRUCTIONS: Record<Direction, string> = {
  hangul_to_translation: 'What does it mean?',
  translation_to_hangul: 'How is it said in Korean?',
  voice_to_hangul: 'Listen, then write it in Korean.',
  voice_to_translation: 'Listen: what does it mean?',
}

const HEADINGS: Record<SessionKind, string> = {
  learn: 'Learn new words',
  review: 'Review due words',
}

/** Whether a question is answered with the Korean, so its options and field are Korean. */
function answeredInKorean(direction: Direction): boolean {
  return direction === 'translation_to_hangul' || direction === 'voice_to_hangul'
}

type Stage =
  | { name: 'start' }
  | {
      name: 'running'
      sessionId: string
      item: Presentation | Question
      verdict: SessionVerdict | null
    }
  /** `next` failed: the session kept its place, so Retry asks for the same item again. */
  | { name: 'failed'; sessionId: string; message: string }
  | { name: 'end'; summary: SessionEnd['summary'] }
  /** The backend no longer knows the session, after a restart for instance. */
  | { name: 'gone' }

function isGone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404
}

/** One learn or review session: the start form, then each item, then the summary. */
export function SessionPage({ kind }: { kind: SessionKind }) {
  const [stage, setStage] = useState<Stage>({ name: 'start' })
  const [busy, setBusy] = useState(false)
  const [answerError, setAnswerError] = useState<string | null>(null)

  async function loadNext(sessionId: string): Promise<void> {
    setBusy(true)
    setAnswerError(null)
    try {
      const item = await fetchNextItem(sessionId)
      setStage(
        item.type === 'end'
          ? { name: 'end', summary: item.summary }
          : { name: 'running', sessionId, item, verdict: null },
      )
    } catch (err) {
      setStage(isGone(err) ? { name: 'gone' } : { name: 'failed', sessionId, message: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function submit(answer: SessionAnswer): Promise<void> {
    if (stage.name !== 'running' || stage.verdict !== null || busy) {
      return
    }
    setBusy(true)
    setAnswerError(null)
    try {
      const verdict = await answerItem(stage.item.item_id, answer)
      setStage({ ...stage, verdict })
    } catch (err) {
      if (isGone(err)) {
        setStage({ name: 'gone' })
      } else {
        setAnswerError(errorMessage(err))
      }
    } finally {
      setBusy(false)
    }
  }

  // Once a verdict is on screen, Enter anywhere moves on, as the numbers page does; never an
  // Enter an input method is still composing with. A layout effect, so the listener arrives
  // in the same commit as the verdict.
  const answered = stage.name === 'running' && stage.verdict !== null
  const onAnsweredEnter = useEffectEvent(() => {
    if (stage.name === 'running' && !busy) {
      void loadNext(stage.sessionId)
    }
  })
  useLayoutEffect(() => {
    if (!answered) {
      return
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (!isSubmitEnter(event)) {
        return
      }
      event.preventDefault()
      onAnsweredEnter()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [answered])

  return (
    <PageLayout>
      <header className="text-center">
        <h1 className="text-4xl text-primary sm:text-5xl">{HEADINGS[kind]}</h1>
      </header>
      {stage.name === 'start' && (
        <StartForm
          kind={kind}
          onStarted={(sessionId) => void loadNext(sessionId)}
          loadingFirst={busy}
        />
      )}
      {stage.name === 'running' && (
        <Card className="flex flex-col gap-5">
          <ProgressLine item={stage.item} />
          {stage.item.type === 'presentation' ? (
            <PresentationView
              presentation={stage.item}
              busy={busy}
              onContinue={() => void loadNext(stage.sessionId)}
            />
          ) : (
            <QuestionView
              key={stage.item.item_id}
              question={stage.item}
              verdict={stage.verdict}
              busy={busy}
              onAnswer={(answer) => void submit(answer)}
            />
          )}
          {answerError !== null && (
            <Feedback tone="error" role="alert">
              {answerError}
            </Feedback>
          )}
          {stage.verdict !== null && (
            <Button
              variant="secondary"
              className="self-end"
              disabled={busy}
              onClick={() => void loadNext(stage.sessionId)}
            >
              Next
            </Button>
          )}
        </Card>
      )}
      {stage.name === 'failed' && (
        <Card className="flex flex-col gap-4">
          <Feedback tone="error" role="alert">
            {stage.message}
          </Feedback>
          <Button className="self-start" disabled={busy} onClick={() => void loadNext(stage.sessionId)}>
            Retry
          </Button>
        </Card>
      )}
      {stage.name === 'end' && (
        <SummaryView summary={stage.summary} onAgain={() => setStage({ name: 'start' })} />
      )}
      {stage.name === 'gone' && (
        <Card className="flex flex-col gap-4">
          <Feedback tone="warning" role="alert">
            This session has ended.
          </Feedback>
          <Button className="self-start" onClick={() => setStage({ name: 'start' })}>
            Start a new session
          </Button>
        </Card>
      )}
    </PageLayout>
  )
}

function StartForm({
  kind,
  onStarted,
  loadingFirst,
}: {
  kind: SessionKind
  onStarted: (sessionId: string) => void
  loadingFirst: boolean
}) {
  const [tags, setTags] = useState<TagCount[]>([])
  const [tag, setTag] = useState('')
  const [count, setCount] = useState<number | null>(null)
  const [directions, setDirections] = useState<Direction[]>(DIRECTIONS)
  const [size, setSize] = useState('')
  const [starting, setStarting] = useState(false)
  const [refusal, setRefusal] = useState<{ message: string; nothingToDo: boolean } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchTags()
      .then((data) => {
        if (!cancelled) {
          setTags(data.tags)
        }
      })
      .catch(() => {
        // The filter is optional: without tags, a session over every word still works.
      })
    return () => {
      cancelled = true
    }
  }, [])

  // How many words the session could take, for the chosen tag: from the word list's summary.
  useEffect(() => {
    let cancelled = false
    fetchWords(tag === '' ? null : tag)
      .then((data) => {
        if (!cancelled) {
          setCount(kind === 'learn' ? data.summary.new : data.summary.due)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCount(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [kind, tag])

  function toggle(direction: Direction): void {
    setDirections((current) =>
      current.includes(direction)
        ? current.filter((one) => one !== direction)
        : DIRECTIONS.filter((one) => one === direction || current.includes(one)),
    )
  }

  async function start(): Promise<void> {
    const params: StartSessionParams = { kind, directions }
    if (tag !== '') {
      params.tag = tag
    }
    if (size.trim() !== '') {
      params.size = Number(size)
    }
    setStarting(true)
    setRefusal(null)
    try {
      const session = await startSession(params)
      onStarted(session.session_id)
    } catch (err) {
      setRefusal({
        message: errorMessage(err),
        nothingToDo: err instanceof ApiError && err.status === 409,
      })
      setStarting(false)
    }
  }

  const busy = starting || loadingFirst
  const words = count === 1 ? 'word' : 'words'
  const countLine = count === null ? null : kind === 'learn' ? `${count} new ${words}` : `${count} ${words} due`

  return (
    <Card className="flex flex-col gap-5">
      {countLine !== null && <p className="text-center text-lg font-bold">{countLine}</p>}
      <Field label="Tag" as="select" value={tag} onChange={(event) => setTag(event.target.value)}>
        <option value="">All tags</option>
        {tags.map((entry) => (
          <option key={entry.tag} value={entry.tag}>
            {entry.tag}
          </option>
        ))}
      </Field>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1.5 text-sm font-bold text-muted">Directions</legend>
        {DIRECTIONS.map((direction) => (
          <label key={direction} className="flex min-h-12 cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              className="size-5 cursor-pointer accent-primary"
              checked={directions.includes(direction)}
              onChange={() => toggle(direction)}
            />
            {directionLabel(direction)}
          </label>
        ))}
      </fieldset>
      <Field
        label="Number of words (empty for the usual)"
        type="number"
        inputMode="numeric"
        min={1}
        value={size}
        onChange={(event) => setSize(event.target.value)}
      />
      {refusal !== null && (
        <Feedback tone={refusal.nothingToDo ? 'warning' : 'error'} role="alert">
          {refusal.message}
        </Feedback>
      )}
      {refusal?.nothingToDo && (
        <TextLink className="self-start" href={routeHref({ page: 'words' })}>
          Go to your words
        </TextLink>
      )}
      <Button className="self-end" disabled={busy || directions.length === 0} onClick={() => void start()}>
        Start
      </Button>
    </Card>
  )
}

function ProgressLine({ item }: { item: Presentation | Question }) {
  const { done, total } = item.progress
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm font-bold text-muted">
      <span>
        {done} of {total} {total === 1 ? 'word' : 'words'} done
      </span>
      {item.type === 'question' && !item.scored && <span>Practice: not scored</span>}
    </div>
  )
}

/** A large play button for an item's audio: autoplay is only attempted, phones block it. */
function AudioButton({ url, label }: { url: string; label: string }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    audioRef.current?.play().catch(() => {})
  }, [url])

  return (
    <div className="flex flex-col items-center gap-2">
      {/* No native controls: the button is the play control. */}
      <audio ref={audioRef} src={url} onError={() => setFailed(true)} />
      <Button round aria-label={label} onClick={() => void audioRef.current?.play().catch(() => {})}>
        <ReplayIcon />
      </Button>
      {failed && <p className="text-sm font-bold text-muted">Audio unavailable.</p>}
    </div>
  )
}

function PresentationView({
  presentation,
  busy,
  onContinue,
}: {
  presentation: Presentation
  busy: boolean
  onContinue: () => void
}) {
  return (
    <div className="flex flex-col items-center gap-4 text-center">
      <p className="text-sm font-bold text-muted">A new word</p>
      <p lang="ko" className="font-display text-5xl text-primary">
        {presentation.korean}
      </p>
      <p className="text-lg">{presentation.translations.join('; ')}</p>
      <AudioButton url={presentation.audio_url} label="Play the word" />
      <Button className="self-end" disabled={busy} onClick={onContinue}>
        Continue
      </Button>
    </div>
  )
}

function QuestionView({
  question,
  verdict,
  busy,
  onAnswer,
}: {
  question: Question
  verdict: SessionVerdict | null
  busy: boolean
  onAnswer: (answer: SessionAnswer) => void
}) {
  const locked = busy || verdict !== null
  const korean = answeredInKorean(question.direction)

  return (
    <div className="flex flex-col gap-4">
      <p className="text-center font-bold text-muted">{DIRECTION_INSTRUCTIONS[question.direction]}</p>
      {question.prompt !== null && (
        <p
          lang={question.direction === 'hangul_to_translation' ? 'ko' : undefined}
          className="text-center font-display text-4xl text-primary"
        >
          {question.prompt}
        </p>
      )}
      {question.audio_url !== null && <AudioButton url={question.audio_url} label="Play the word" />}
      {question.options !== null ? (
        <ul className="flex flex-col gap-3">
          {question.options.map((option, index) => {
            const right = verdict !== null && option === verdict.correct_option
            return (
              <li key={index}>
                <Button
                  variant={right ? 'primary' : 'secondary'}
                  lang={korean ? 'ko' : undefined}
                  className="w-full"
                  disabled={locked}
                  onClick={() => onAnswer({ choice: index })}
                >
                  {right && <CheckIcon />}
                  {option}
                </Button>
              </li>
            )
          })}
        </ul>
      ) : (
        <TypedAnswer korean={korean} locked={locked} onAnswer={onAnswer} />
      )}
      <Button variant="subtle" className="self-start" disabled={locked} onClick={() => onAnswer({ dont_know: true })}>
        I don&apos;t know
      </Button>
      {verdict !== null && <VerdictView question={question} verdict={verdict} />}
    </div>
  )
}

function TypedAnswer({
  korean,
  locked,
  onAnswer,
}: {
  korean: boolean
  locked: boolean
  onAnswer: (answer: SessionAnswer) => void
}) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { lang: _lang, ...latinInput } = KOREAN_INPUT
  const inputAttributes = korean ? KOREAN_INPUT : latinInput

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  function send(): void {
    if (!locked && text.trim() !== '') {
      onAnswer({ answer: text })
    }
  }

  return (
    <div className="flex items-end gap-3">
      <Field
        ref={inputRef}
        className="min-w-0 flex-1"
        label={korean ? 'Your answer, in Korean' : 'Your answer'}
        type="text"
        {...inputAttributes}
        value={text}
        disabled={locked}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (isSubmitEnter(event)) {
            event.preventDefault()
            send()
          }
        }}
      />
      <Button disabled={locked || text.trim() === ''} onClick={send}>
        Submit
      </Button>
    </div>
  )
}

function VerdictView({ question, verdict }: { question: Question; verdict: SessionVerdict }) {
  const wrongChoice = !verdict.correct && verdict.correct_option !== null
  return (
    <div className="flex flex-col gap-3">
      <Feedback tone={verdict.correct ? 'success' : 'error'}>
        <p>{verdict.correct ? 'Right!' : 'Not this time.'}</p>
        <p>
          <span lang="ko">{verdict.korean}</span>: {verdict.translations.join('; ')}
        </p>
        {wrongChoice && <p>The right answer: {verdict.correct_option}</p>}
      </Feedback>
      <ScoreChange question={question} verdict={verdict} />
    </div>
  )
}

function ScoreChange({ question, verdict }: { question: Question; verdict: SessionVerdict }) {
  const { statistics_before: before, statistics_after: after } = verdict
  if (!verdict.scored || before === null || after === null) {
    return (
      <p className="text-sm font-bold text-muted">
        {question.scored ? 'Not scored: this word was deleted.' : 'Practice question: not scored.'}
      </p>
    )
  }
  const now = new Date()
  const rows: [string, ReactNode][] = [
    ['Score', `${formatScore(before.score)} → ${formatScore(after.score)}`],
    ['Stability', `${stabilityOf(before)} → ${stabilityOf(after)}`],
    ['Next review', `${nextReviewOf(after, now)} (was ${nextReviewOf(before, now)})`],
  ]
  return (
    <dl className="flex flex-col gap-1.5">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-wrap justify-between gap-2">
          <dt className="text-muted">{label}</dt>
          <dd className="font-bold">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function stabilityOf(statistics: WordStatistics): string {
  return statistics.stability === null ? 'New' : formatDays(statistics.stability)
}

function nextReviewOf(statistics: WordStatistics, now: Date): string {
  return formatDue(statistics, now) ?? 'none yet'
}

function SummaryView({ summary, onAgain }: { summary: SessionEnd['summary']; onAgain: () => void }) {
  return (
    <Card className="flex flex-col gap-4">
      <h2 className="text-2xl text-primary">Session complete</h2>
      <p className="font-bold">
        {summary.correct_count} of {summary.word_count} right at the first try
      </p>
      <ul className="flex flex-col gap-2">
        {summary.words.map((word, index) => (
          <li key={index} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span lang="ko" className="font-bold">
                {word.korean}
              </span>
              : {word.translations.join('; ')}
            </span>
            <span className="text-sm font-bold text-muted">{word.correct ? 'right' : 'missed'}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <TextLink href={routeHref({ page: 'words' })}>See your words</TextLink>
        <Button onClick={onAgain}>Start another session</Button>
      </div>
    </Card>
  )
}
