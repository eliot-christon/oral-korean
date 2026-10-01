import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  createDateQuestion,
  errorMessage,
  fetchDateYearRange,
  submitDateAnswer,
  type DateAnswerResponse,
  type DateSelection,
  type YearRange,
} from '../api'
import { Button } from '../components/Button'
import { CalendarPicker } from '../components/CalendarPicker'
import { monthName, type YearMonth } from '../components/calendarGrid'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { ReplayIcon } from '../components/icons'
import { PageLayout } from './PageLayout'

interface PendingQuestion {
  questionId: string
  audioUrl: string
  asksYear: boolean
}

/** A date in digits and English, the way the calendar names its days: "6 June 2026". */
function dateText({ year, month, day }: DateSelection): string {
  const text = `${day} ${monthName(month)}`
  return year === null ? text : `${text} ${year}`
}

function feedbackMessage(result: DateAnswerResponse): ReactNode {
  // `lang="ko"` so the Hangul face and screen readers treat the reading as Korean.
  const answer = (
    <>
      It was {dateText(result.expected)} (<span lang="ko">{result.text}</span>).
    </>
  )
  return result.verdict === 'correct' ? <>Correct! {answer}</> : <>Incorrect. {answer}</>
}

/**
 * The month the calendar opens on: the current one, never one derived from the question. For
 * a dated question its year is clamped into the window; a yearless one lays the grid out in
 * the current year.
 */
function neutralMonth(asksYear: boolean, range: YearRange): YearMonth {
  const today = new Date()
  const year = today.getFullYear()
  return {
    year: asksYear ? Math.min(Math.max(year, range.minimum), range.maximum) : year,
    month: today.getMonth() + 1,
  }
}

/**
 * The calendar exercise: a date is heard in Korean and picked on the calendar, with its year
 * when the question speaks one. The answer (the date and its Korean) only arrives with the
 * verdict, after Submit.
 */
export function DatePage() {
  const [yearRange, setYearRange] = useState<YearRange | null>(null)
  const [question, setQuestion] = useState<PendingQuestion | null>(null)
  const [selection, setSelection] = useState<DateSelection | null>(null)
  const [feedback, setFeedback] = useState<DateAnswerResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  // A question in hand with no verdict yet: Next stays locked, so a date cannot be skipped
  // unanswered. Any day can be submitted as a best guess, so there is no reveal.
  const awaitingVerdict = question !== null && feedback === null

  async function drawQuestion(): Promise<void> {
    setError(null)
    setFeedback(null)
    setSelection(null)
    setQuestion(null)
    try {
      const response = await createDateQuestion()
      setQuestion({
        questionId: response.question_id,
        audioUrl: response.audio_url,
        asksYear: response.asks_year,
      })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  // The year window, then the first question: once, on arrival.
  useEffect(() => {
    let cancelled = false
    fetchDateYearRange()
      .then((range) => {
        if (cancelled) {
          return
        }
        setYearRange(range)
        void drawQuestion()
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

  function handleReplay(): void {
    audioRef.current?.play().catch(() => {})
  }

  async function handleSubmit(): Promise<void> {
    if (!question || selection === null || feedback !== null) {
      return
    }
    try {
      setFeedback(await submitDateAnswer(question.questionId, selection))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <PageLayout>
      <header className="text-center">
        <h1 className="text-4xl text-primary sm:text-5xl">Dates</h1>
        <p className="mt-1 text-muted">Listen, then pick the day you heard on the calendar.</p>
      </header>
      {error && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {yearRange === null ? (
        !error && <p className="text-center text-muted">Loading...</p>
      ) : (
        <Card className="flex flex-col items-center gap-6">
          {/* No native controls: the Replay button is the play control. */}
          {question && <audio ref={audioRef} src={question.audioUrl} />}

          <Button round aria-label="Replay" onClick={handleReplay} disabled={!question}>
            <ReplayIcon />
          </Button>

          {question && (
            <>
              <p className="text-center text-sm text-muted">
                {question.asksYear ? 'The year is spoken: pick it too.' : 'No year this time.'}
              </p>
              {/* Keyed by question: every question opens the calendar afresh, on the neutral month. */}
              <CalendarPicker
                key={question.questionId}
                value={selection}
                onChange={setSelection}
                yearRange={question.asksYear ? yearRange : null}
                initialMonth={neutralMonth(question.asksYear, yearRange)}
              />
            </>
          )}

          <Button
            className="w-full sm:w-auto"
            onClick={() => void handleSubmit()}
            disabled={!awaitingVerdict || selection === null}
          >
            Submit
          </Button>

          {feedback && (
            <div className="w-full">
              <Feedback tone={feedback.verdict === 'correct' ? 'success' : 'error'}>
                {feedbackMessage(feedback)}
              </Feedback>
            </div>
          )}

          <Button variant="secondary" className="self-end" onClick={() => void drawQuestion()} disabled={awaitingVerdict}>
            Next
          </Button>
        </Card>
      )}
    </PageLayout>
  )
}
