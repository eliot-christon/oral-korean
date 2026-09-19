import { useEffect, useRef, useState } from 'react'

import './styles.css'
import {
  createQuestion,
  fetchSystems,
  submitAnswer,
  type AnswerResponse,
  type NumeralSystem,
  type NumeralSystemInfo,
} from './api'

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

function feedbackMessage(result: AnswerResponse): string {
  if (result.verdict === 'correct') {
    return 'Correct!'
  }
  if (result.verdict === 'incorrect') {
    return `Incorrect. The answer was ${result.expected_number} (${result.text}).`
  }
  return 'That is not a number. Type the digits you heard.'
}

function App() {
  const [systems, setSystems] = useState<NumeralSystemInfo[] | null>(null)
  const [selectedSystem, setSelectedSystem] = useState<NumeralSystem>('sino')
  const [maximumOverride, setMaximumOverride] = useState<number | null>(null)
  const [question, setQuestion] = useState<PendingQuestion | null>(null)
  const [answerValue, setAnswerValue] = useState('')
  const [feedback, setFeedback] = useState<AnswerResponse | null>(null)
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

  async function drawQuestion(system: NumeralSystem, maximum: number): Promise<void> {
    setError(null)
    setFeedback(null)
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
  // deliberately not a dependency (oxlint's exhaustive-deps warning on this hook is
  // expected and left in place): a system change afterwards is drawn once, from the
  // selector's own `onChange` (`handleSystemChange`) - adding the dependency here would
  // draw a second, redundant question on every change.
  useEffect(() => {
    if (systems === null) {
      return
    }
    const info = systems.find((entry) => entry.system === selectedSystem)
    if (info) {
      // oxlint-disable-next-line react/set-state-in-effect -- syncing with fetched data
      void drawQuestion(selectedSystem, info.maximum)
    }
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

  async function handleSubmit(): Promise<void> {
    if (!question || !answerValue.trim()) {
      return
    }
    try {
      const result = await submitAnswer(question.questionId, answerValue)
      setFeedback(result)
    } catch (err) {
      setError(errorMessageOf(err, 'Could not submit the answer. Is the backend running?'))
    }
  }

  return (
    <main>
      <h1>Oral Korean</h1>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {systems === null ? (
        <p>Loading numeral systems...</p>
      ) : (
        <>
          <label className="field">
            Numeral system
            <select
              aria-label="Numeral system"
              value={selectedSystem}
              onChange={(event) => handleSystemChange(event.target.value as NumeralSystem)}
            >
              {systems.map((entry) => (
                <option key={entry.system} value={entry.system}>
                  {systemLabel(entry.system)}
                </option>
              ))}
            </select>
          </label>

          {systemInfo && (
            <label className="field">
              Maximum
              <input
                type="number"
                aria-label="Maximum"
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
            </label>
          )}

          {question && <audio ref={audioRef} src={question.audioUrl} controls />}

          <div className="controls">
            <button type="button" onClick={handleReplay} disabled={!question}>
              Replay
            </button>
            <button type="button" onClick={handleNext} disabled={!systemInfo}>
              Next
            </button>
          </div>

          <div className="field">
            <label>
              Answer
              <input
                type="text"
                aria-label="Answer"
                value={answerValue}
                onChange={(event) => setAnswerValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void handleSubmit()
                  }
                }}
              />
            </label>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!question || !answerValue.trim()}
            >
              Submit
            </button>
          </div>

          {feedback && (
            <p role="status" className={`feedback feedback-${feedback.verdict}`}>
              {feedbackMessage(feedback)}
            </p>
          )}
        </>
      )}
    </main>
  )
}

export default App
