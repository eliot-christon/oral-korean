import { useEffect, useEffectEvent, useState } from 'react'

import {
  errorMessage,
  fetchLearnQueue,
  fetchReviewCandidates,
  reorderLearnQueue,
  type Direction,
  type QueuedWord,
  type ReviewCandidate,
} from '../api'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Feedback } from '../components/Feedback'

type Move = 'up' | 'down' | 'top'

/** `ids` with the one at `index` moved one place up or down, or to the top. */
function moved(ids: number[], index: number, move: Move): number[] {
  const target = move === 'top' ? 0 : move === 'up' ? index - 1 : index + 1
  const next = ids.filter((_, position) => position !== index)
  next.splice(target, 0, ids[index])
  return next
}

/** The word as the lists show it: its Korean, marked as such, then its translations. */
function WordText({ word }: { word: QueuedWord }) {
  return (
    <span className="min-w-0 flex-1">
      <span lang="ko" className="font-bold">
        {word.korean}
      </span>{' '}
      <span className="text-muted">{word.translations.join('; ')}</span>
    </span>
  )
}

/** Up, down and to the top, each named with the word; the ones that would go nowhere disabled. */
function MoveButtons({
  word,
  index,
  count,
  disabled,
  onMove,
}: {
  word: QueuedWord
  index: number
  count: number
  disabled: boolean
  onMove: (move: Move) => void
}) {
  const buttons: [Move, string, string, boolean][] = [
    ['top', '⤒', `Move ${word.korean} to top`, index === 0],
    ['up', '↑', `Move ${word.korean} up`, index === 0],
    ['down', '↓', `Move ${word.korean} down`, index === count - 1],
  ]
  return (
    <span className="flex gap-1">
      {buttons.map(([move, glyph, label, atTheEnd]) => (
        <Button
          key={move}
          variant="subtle"
          aria-label={label}
          disabled={disabled || atTheEnd}
          onClick={() => onMove(move)}
        >
          <span aria-hidden="true">{glyph}</span>
        </Button>
      ))}
    </span>
  )
}

/**
 * The learn queue for a tag and the ticked directions, top first: the first `batchSize` words
 * are the next session's. Every move is saved at once, and the order shown is the one the
 * backend answers with, never an assumed one; a failed move leaves the list as it was.
 */
export function LearnQueue({
  tag,
  directions,
  batchSize,
}: {
  tag: string | null
  directions: Direction[]
  batchSize: number
}) {
  const [words, setWords] = useState<QueuedWord[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchLearnQueue(tag, directions)
      .then((queue) => {
        if (!cancelled) {
          setWords(queue)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [tag, directions])

  async function move(index: number, how: Move): Promise<void> {
    if (words === null) {
      return
    }
    const ids = words.map((word) => word.id)
    // To the top is one word; up or down sends the whole list shown, in its new order. With a
    // tag, those words go to the top of the queue and the others keep their order after them.
    const request = how === 'top' ? [ids[index]] : moved(ids, index, how)
    setSaving(true)
    setError(null)
    try {
      const queue = await reorderLearnQueue(request)
      const shown = new Set(ids)
      setWords(queue.filter((word) => shown.has(word.id)))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-bold text-muted">Learn queue, next first</h2>
      {error !== null && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {words !== null && words.length === 0 && <p className="text-muted">Nothing left to learn here.</p>}
      {words !== null && words.length > 0 && (
        <ol aria-label="Learn queue" className="flex flex-col gap-2">
          {words.map((word, index) => (
            <li key={word.id} className="flex flex-wrap items-center gap-2">
              <WordText word={word} />
              {index < batchSize && <Badge tone="highlight">Next session</Badge>}
              <MoveButtons
                word={word}
                index={index}
                count={words.length}
                disabled={saving}
                onMove={(how) => void move(index, how)}
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

/**
 * The words a review can cover, for a tag and the ticked directions: the due ones selected at
 * first, the others offered to review early. The selected words are ordered with the same
 * buttons as the learn queue. Nothing is stored: `onSelection` reports the chosen ids, in
 * order, or `null` while the candidates are not known.
 */
export function ReviewPicker({
  tag,
  directions,
  onSelection,
}: {
  tag: string | null
  directions: Direction[]
  onSelection: (wordIds: number[] | null) => void
}) {
  const [candidates, setCandidates] = useState<ReviewCandidate[] | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const report = useEffectEvent((wordIds: number[] | null) => onSelection(wordIds))

  useEffect(() => {
    let cancelled = false
    // Until the new candidates are in, a start goes without a choice: never with the old one.
    report(null)
    fetchReviewCandidates(tag, directions)
      .then((words) => {
        if (!cancelled) {
          const due = words.filter((word) => word.due).map((word) => word.id)
          setCandidates(words)
          setSelected(due)
          setError(null)
          report(due)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [tag, directions])

  function choose(next: number[]): void {
    setSelected(next)
    onSelection(next)
  }

  const byId = new Map((candidates ?? []).map((word) => [word.id, word]))
  const chosen = selected.map((id) => byId.get(id)).filter((word) => word !== undefined)
  const others = (candidates ?? []).filter((word) => !selected.includes(word.id))

  return (
    <section className="flex flex-col gap-2">
      {error !== null && (
        <Feedback tone="error" role="alert">
          {error}
        </Feedback>
      )}
      {candidates !== null && candidates.length === 0 && (
        <p className="text-muted">Nothing learned here yet.</p>
      )}
      {chosen.length > 0 && (
        <>
          <h2 className="text-sm font-bold text-muted">To review, in this order</h2>
          <ol aria-label="Words to review" className="flex flex-col gap-2">
            {chosen.map((word, index) => (
              <li key={word.id} className="flex flex-wrap items-center gap-2">
                <PickBox word={word} checked onToggle={() => choose(selected.filter((id) => id !== word.id))} />
                <MoveButtons
                  word={word}
                  index={index}
                  count={chosen.length}
                  disabled={false}
                  onMove={(how) => choose(moved(selected, index, how))}
                />
              </li>
            ))}
          </ol>
        </>
      )}
      {others.length > 0 && (
        <>
          <h2 className="text-sm font-bold text-muted">Not selected</h2>
          <ul aria-label="Words not selected" className="flex flex-col gap-2">
            {others.map((word) => (
              <li key={word.id} className="flex flex-wrap items-center gap-2">
                <PickBox word={word} checked={false} onToggle={() => choose([...selected, word.id])} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/** A candidate's checkbox, labelled with the word and whether it is due. */
function PickBox({
  word,
  checked,
  onToggle,
}: {
  word: ReviewCandidate
  checked: boolean
  onToggle: () => void
}) {
  return (
    <label className="flex min-h-12 min-w-0 flex-1 cursor-pointer items-center gap-3">
      <input type="checkbox" className="size-5 cursor-pointer accent-primary" checked={checked} onChange={onToggle} />
      <WordText word={word} />
      <Badge tone={word.due ? 'score' : 'tag'}>{word.due ? 'Due' : 'Not due yet'}</Badge>
    </label>
  )
}
