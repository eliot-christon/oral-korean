import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import {
  createQuestion,
  fetchSystems,
  submitAnswer,
  type AnswerResponse,
  type NumeralSystem,
  type NumeralSystemInfo,
} from '../api'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback, type FeedbackTone } from '../components/Feedback'
import { Field } from '../components/Field'
import { ReplayIcon } from '../components/icons'

interface PendingQuestion {
  questionId: string
  audioUrl: string
}

const SYSTEM_LABELS: Record<NumeralSystem, string> = {
  sino: 'Sino-Korean',
  native: 'Native Korean',
}

function systemLabel(system: NumeralSystem): string {
  // `SYSTEM_LABELS` is a `Record<NumeralSystem, string>`, so TypeScript already refuses to
  // compile if a system is added to the union without a label for it here.
  return SYSTEM_LABELS[system]
}

function clampToRange(value: number, info: NumeralSystemInfo): number {
  return Math.min(Math.max(value, info.minimum), info.maximum)
}

function errorMessageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function answerWas(result: AnswerResponse): ReactNode {
  // `lang="ko"` so the Hangul face and screen readers treat the reading as Korean.
  return (
    <>
      The answer was {result.expected_number} (<span lang="ko">{result.text}</span>).
    </>
  )
}

function feedbackMessage(result: AnswerResponse, revealed: boolean): ReactNode {
  if (revealed) {
    return answerWas(result)
  }
  if (result.verdict === 'correct') {
    return 'Correct!'
  }
  if (result.verdict === 'incorrect') {
    return <>Incorrect. {answerWas(result)}</>
  }
  return 'That is not a number. Type the digits you heard.'
}

// A reveal gets its own tone: it is neither a right answer nor a typo, and not a wrong
// answer either, since nothing was guessed.
function feedbackTone(result: AnswerResponse, revealed: boolean): FeedbackTone {
  if (revealed) {
    return 'neutral'
  }
  if (result.verdict === 'correct') {
    return 'success'
  }
  return result.verdict === 'incorrect' ? 'error' : 'warning'
}

export function NumbersPage() {
  const [systems, setSystems] = useState<NumeralSystemInfo[] | null>(null)
  const [selectedSystem, setSelectedSystem] = useState<NumeralSystem>('sino')
  const [maximumOverride, setMaximumOverride] = useState<number | null>(null)
  const [question, setQuestion] = useState<PendingQuestion | null>(null)
  const [answerValue, setAnswerValue] = useState('')
  const [feedback, setFeedback] = useState<AnswerResponse | null>(null)
  // Whether `feedback` came from Show answer rather than from a submitted answer, which is
  // what picks "The answer was ..." over the verdict's own wording, and what lets its
  // `not_a_number` verdict settle the question.
  const [revealed, setRevealed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    let cancelled = false
    fetchSystems()
      .then((data) => {
        if (!cancelled) {
          setSystems(data.systems)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errorMessageOf(err, 'Could not reach the backend. Is it running?'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const systemInfo = systems?.find((entry) => entry.system === selectedSystem) ?? null
  const maximumValue = maximumOverride ?? systemInfo?.maximum ?? null
  // A question is settled once a verdict ends it: right, wrong, or revealed. A typo does
  // not: "not a number" answers nothing, so the user retypes or reveals.
  const settled = feedback !== null && (revealed || feedback.verdict !== 'not_a_number')
  // A question in hand that is not settled yet. Next stays locked while this holds, so a
  // number cannot be skipped unanswered: an answer or Show answer ends it. With no question
  // in hand (a draw failed) there is nothing to skip, and Next is the only way to retry.
  const awaitingVerdict = question !== null && !settled

  async function drawQuestion(system: NumeralSystem, maximum: number): Promise<void> {
    setError(null)
    setFeedback(null)
    setRevealed(false)
    setAnswerValue('')
    setQuestion(null)
    try {
      const response = await createQuestion({ system, maximum })
      setQuestion({ questionId: response.question_id, audioUrl: response.audio_url })
    } catch (err) {
      setError(errorMessageOf(err, 'Could not load a new question. Is the backend running?'))
    }
  }

  // Draws the very first question once the catalogue arrives. `selectedSystem` is
  // deliberately not a dependency (see the oxlint-disable comment below): a system change
  // afterwards is drawn once, from the selector's own `onChange` (`handleSystemChange`) -
  // adding the dependency here would draw a second, redundant question on every change.
  useEffect(() => {
    if (systems === null) {
      return
    }
    const info = systems.find((entry) => entry.system === selectedSystem)
    if (info) {
      // oxlint-disable-next-line react/set-state-in-effect -- syncing with fetched data
      void drawQuestion(selectedSystem, info.maximum)
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- selectedSystem omitted on purpose
  }, [systems])

  function handleSystemChange(system: NumeralSystem): void {
    setSelectedSystem(system)
    setMaximumOverride(null)
    const info = systems?.find((entry) => entry.system === system)
    if (info) {
      void drawQuestion(system, info.maximum)
    }
  }

  useEffect(() => {
    if (question) {
      audioRef.current?.play().catch(() => {})
    }
  }, [question])

  function handleReplay(): void {
    audioRef.current?.play().catch(() => {})
  }

  function handleNext(): void {
    if (!systemInfo || maximumValue === null) {
      return
    }
    void drawQuestion(selectedSystem, maximumValue)
  }

  // The whole loop on one key: Enter in the answer field submits, and once the question is
  // settled, Enter anywhere moves on. Page-wide because a mouse click on Submit or Show
  // answer disables the button it lands on, which leaves focus on the page itself.
  // A layout effect, so the listener arrives in the same commit as the verdict. The verdict
  // lands after a fetch, not an input event, so a passive effect would run a task later:
  // for that moment the verdict is on screen but Enter does nothing.
  const onSettledEnter = useEffectEvent(handleNext)
  useLayoutEffect(() => {
    if (!settled) {
      return
    }
    function handleKeyDown(event: KeyboardEvent): void {
      // Only a fresh press moves on: an auto-repeat of the key that submitted must not skip
      // past the verdict it produced.
      if (event.key !== 'Enter' || event.repeat) {
        return
      }
      // Also cancels a focused button's own Enter activation: Enter on Next must draw one
      // question, not two.
      event.preventDefault()
      onSettledEnter()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [settled])

  async function handleSubmit(): Promise<void> {
    if (!question || settled || !answerValue.trim()) {
      return
    }
    try {
      const result = await submitAnswer(question.questionId, answerValue)
      setFeedback(result)
    } catch (err) {
      setError(errorMessageOf(err, 'Could not submit the answer. Is the backend running?'))
    }
  }

  // A reveal is a deliberate submission of an empty answer, so the answer still only
  // arrives on request. The backend judges an empty string `not_a_number` but, like every
  // verdict, attaches the expected number and its Korean text, so no endpoint of its own
  // is needed. `revealed` keeps that verdict from being worded as a typo.
  async function handleReveal(): Promise<void> {
    if (!question || settled) {
      return
    }
    try {
      const result = await submitAnswer(question.questionId, '')
      setFeedback(result)
      setRevealed(true)
    } catch (err) {
      setError(errorMessageOf(err, 'Could not reveal the answer. Is the backend running?'))
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-6 px-4 py-8 sm:py-12">
      <header className="text-center">
        <h1 className="text-4xl text-primary sm:text-5xl">Oral Korean</h1>
        <p className="mt-1 text-muted">Listen, then type the number you heard.</p>
      </header>
      {error && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {systems === null ? (
        <p className="text-center text-muted">Loading numeral systems...</p>
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_7rem] gap-3">
            <Field
              label="Numeral system"
              as="select"
              value={selectedSystem}
              onChange={(event) => handleSystemChange(event.target.value as NumeralSystem)}
            >
              {systems.map((entry) => (
                <option key={entry.system} value={entry.system}>
                  {systemLabel(entry.system)}
                </option>
              ))}
            </Field>

            {systemInfo && (
              <Field
                label="Maximum"
                type="number"
                min={systemInfo.minimum}
                max={systemInfo.maximum}
                value={maximumValue ?? systemInfo.maximum}
                onChange={(event) => {
                  const value = Number(event.target.value)
                  if (!Number.isNaN(value)) {
                    setMaximumOverride(clampToRange(value, systemInfo))
                  }
                }}
              />
            )}
          </div>

          <Card className="flex flex-col items-center gap-6">
            {/* No native controls: the Replay button is the play control. */}
            {question && <audio ref={audioRef} src={question.audioUrl} />}

            <Button round aria-label="Replay" onClick={handleReplay} disabled={!question}>
              <ReplayIcon />
            </Button>

            <div className="flex w-full items-end gap-3">
              <Field
                className="min-w-0 flex-1"
                label="Answer"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={answerValue}
                onChange={(event) => setAnswerValue(event.target.value)}
                onKeyDown={(event) => {
                  // Once the question is settled, Enter belongs to the page-wide handler.
                  if (event.key !== 'Enter' || event.repeat || settled) {
                    return
                  }
                  event.preventDefault()
                  void handleSubmit()
                }}
              />
              <Button
                onClick={() => void handleSubmit()}
                disabled={!awaitingVerdict || !answerValue.trim()}
              >
                Submit
              </Button>
            </div>

            {feedback && (
              <div className="w-full">
                <Feedback tone={feedbackTone(feedback, revealed)}>
                  {feedbackMessage(feedback, revealed)}
                </Feedback>
              </div>
            )}

            <div className="flex w-full flex-wrap items-center justify-between gap-3">
              <Button
                variant="subtle"
                onClick={() => void handleReveal()}
                disabled={!awaitingVerdict}
              >
                Show answer
              </Button>
              <Button
                variant="secondary"
                onClick={handleNext}
                disabled={!systemInfo || awaitingVerdict}
              >
                Next
              </Button>
            </div>
          </Card>
        </>
      )}
    </main>
  )
}
