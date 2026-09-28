import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  createTimeQuestion,
  errorMessage,
  fetchTimeLevels,
  submitTimeAnswer,
  type ClockSelection,
  type TimeAnswerResponse,
  type TimeLevel,
  type TimeLevelInfo,
} from '../api'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ClockFace } from '../components/ClockFace'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { ReplayIcon } from '../components/icons'
import { PageLayout } from './PageLayout'

interface PendingQuestion {
  questionId: string
  audioUrl: string
  minuteStep: number
}

const LEVEL_LABELS: Record<TimeLevel, string> = {
  half_hour: 'On the hour and half past',
  five_minutes: 'Every 5 minutes',
  any_minute: 'Any minute',
}

// Every question starts here, never at a position derived from the question.
const NEUTRAL: ClockSelection = { period: 'am', hour: 12, minute: 0 }

/** A clock position in digits, the way the clock's own readout shows it: "3:05 PM". */
function clockText({ period, hour, minute }: ClockSelection): string {
  return `${hour}:${String(minute).padStart(2, '0')} ${period === 'am' ? 'AM' : 'PM'}`
}

function feedbackMessage(result: TimeAnswerResponse): ReactNode {
  // `lang="ko"` so the Hangul face and screen readers treat the reading as Korean.
  const answer = (
    <>
      It was {clockText(result.expected)} (<span lang="ko">{result.text}</span>).
    </>
  )
  return result.verdict === 'correct' ? <>Correct! {answer}</> : <>Incorrect. {answer}</>
}

/**
 * The clock exercise: a time is heard in Korean and set on the clock. The answer (the time
 * and its Korean) only arrives with the verdict, after Submit.
 */
export function TimePage() {
  const [levels, setLevels] = useState<TimeLevelInfo[] | null>(null)
  const [level, setLevel] = useState<TimeLevel | null>(null)
  const [question, setQuestion] = useState<PendingQuestion | null>(null)
  const [selection, setSelection] = useState<ClockSelection>(NEUTRAL)
  const [feedback, setFeedback] = useState<TimeAnswerResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  // A question in hand with no verdict yet: Next stays locked, so a time cannot be skipped
  // unanswered. A clock always holds a time, so submitting a guess is how to see the answer.
  const awaitingVerdict = question !== null && feedback === null
  const levelInfo = levels?.find((entry) => entry.level === level)
  const minuteStep = question?.minuteStep ?? levelInfo?.minute_step ?? 5

  async function drawQuestion(chosen: TimeLevel): Promise<void> {
    setError(null)
    setFeedback(null)
    setSelection(NEUTRAL)
    setQuestion(null)
    try {
      const response = await createTimeQuestion(chosen)
      setQuestion({
        questionId: response.question_id,
        audioUrl: response.audio_url,
        minuteStep: response.minute_step,
      })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  // The catalogue, then the first question at its default level: once, on arrival.
  useEffect(() => {
    let cancelled = false
    fetchTimeLevels()
      .then((data) => {
        if (cancelled) {
          return
        }
        setLevels(data.levels)
        setLevel(data.default)
        void drawQuestion(data.default)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (question) {
      audioRef.current?.play().catch(() => {})
    }
  }, [question])

  function handleLevelChange(chosen: TimeLevel): void {
    setLevel(chosen)
    void drawQuestion(chosen)
  }

  function handleReplay(): void {
    audioRef.current?.play().catch(() => {})
  }

  function handleNext(): void {
    if (level !== null) {
      void drawQuestion(level)
    }
  }

  async function handleSubmit(): Promise<void> {
    if (!question || feedback !== null) {
      return
    }
    try {
      setFeedback(await submitTimeAnswer(question.questionId, selection))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <PageLayout>
      <header className="text-center">
        <h1 className="text-4xl text-primary sm:text-5xl">Time</h1>
        <p className="mt-1 text-muted">Listen, then set the clock to the time you heard.</p>
      </header>
      {error && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {levels === null ? (
        !error && <p className="text-center text-muted">Loading levels...</p>
      ) : (
        <>
          <Field
            label="Minutes"
            as="select"
            value={level ?? ''}
            onChange={(event) => handleLevelChange(event.target.value as TimeLevel)}
          >
            {levels.map((entry) => (
              <option key={entry.level} value={entry.level}>
                {LEVEL_LABELS[entry.level]}
              </option>
            ))}
          </Field>

          <Card className="flex flex-col items-center gap-6">
            {/* No native controls: the Replay button is the play control. */}
            {question && <audio ref={audioRef} src={question.audioUrl} />}

            <Button round aria-label="Replay" onClick={handleReplay} disabled={!question}>
              <ReplayIcon />
            </Button>

            <ClockFace value={selection} minuteStep={minuteStep} onChange={setSelection} />

            <Button className="w-full sm:w-auto" onClick={() => void handleSubmit()} disabled={!awaitingVerdict}>
              Submit
            </Button>

            {feedback && (
              <div className="w-full">
                <Feedback tone={feedback.verdict === 'correct' ? 'success' : 'error'}>
                  {feedbackMessage(feedback)}
                </Feedback>
              </div>
            )}

            <Button variant="secondary" className="self-end" onClick={handleNext} disabled={level === null || awaitingVerdict}>
              Next
            </Button>
          </Card>
        </>
      )}
    </PageLayout>
  )
}
