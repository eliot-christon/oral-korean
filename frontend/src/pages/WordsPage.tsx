import { useEffect, useState } from 'react'

import {
  errorMessage,
  fetchTags,
  fetchWords,
  type TagCount,
  type VocabularySummary,
  type Word,
  type WordListResponse,
} from '../api'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { TextLink } from '../components/TextLink'
import { formatDue, formatPercent, formatScore } from '../format'
import { useNotice } from '../notice'
import { routeHref } from '../routes'
import { PageLayout } from './PageLayout'

// The `<select>` value that stands for no filter: a tag is never empty.
const ALL_TAGS = ''

function SummaryTiles({ summary }: { summary: VocabularySummary }) {
  const tiles: [string, string][] = [
    ['Words', String(summary.total)],
    ['New', String(summary.new)],
    ['Due now', String(summary.due)],
    // Every listed word new: there is no average, and 0% would claim one.
    ['Average score', summary.average_score === null ? '-' : formatPercent(summary.average_score)],
  ]
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map(([label, value]) => (
        <div key={label} className="flex flex-col-reverse rounded-card bg-surface p-4 shadow-soft">
          <dt className="text-sm font-bold text-muted">{label}</dt>
          <dd className="font-display text-3xl text-primary">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function WordCard({ word, now }: { word: Word; now: Date }) {
  const { statistics } = word
  const due = formatDue(statistics, now)
  return (
    <a
      href={routeHref({ page: 'word', id: word.id })}
      className="block rounded-card focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      <Card className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p lang="ko" className="font-display text-3xl wrap-break-word text-ink">
              {word.korean}
            </p>
            <p className="text-muted">{word.translations.join('; ')}</p>
          </div>
          <Badge tone={statistics.score === null ? 'highlight' : 'score'}>
            <span className="sr-only">Score: </span>
            {formatScore(statistics.score)}
          </Badge>
        </div>
        {(word.tags.length > 0 || due !== null) && (
          <div className="flex flex-wrap items-center gap-2">
            {word.tags.map((tag) => (
              <Badge key={tag} tone="tag">
                {tag}
              </Badge>
            ))}
            {due !== null &&
              (statistics.due ? (
                <Badge tone="highlight">{due}</Badge>
              ) : (
                <span className="text-sm font-semibold text-muted">Next review {due}</span>
              ))}
          </div>
        )}
      </Card>
    </a>
  )
}

const ADD_WORDS_HREF = routeHref({ page: 'addWords' })

function EmptyState({ tag }: { tag: string | null }) {
  return (
    <Card className="flex flex-col items-center gap-2 text-center text-muted">
      {tag === null ? (
        <>
          <p>No words yet.</p>
          <TextLink href={ADD_WORDS_HREF}>Add your first words</TextLink>
        </>
      ) : (
        <p>No word carries the tag {tag}.</p>
      )}
    </Card>
  )
}

/** Every word with its score and when it is due, a summary, and a filter by tag. */
export function WordsPage() {
  // "Added 2 words." after a paste, "Deleted 사과." after a delete.
  const notice = useNotice()
  // The filter is page state, not part of the address.
  const [tag, setTag] = useState<string | null>(null)
  const [list, setList] = useState<WordListResponse | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [tags, setTags] = useState<TagCount[]>([])
  const [tagsError, setTagsError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchTags()
      .then((response) => {
        if (!cancelled) {
          setTags(response.tags)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setTagsError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchWords(tag)
      .then((response) => {
        if (!cancelled) {
          setList(response)
          setListError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setListError(errorMessage(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [tag])

  const now = new Date()

  return (
    <PageLayout>
      <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h1 className="text-4xl text-primary sm:text-5xl">Words</h1>
          <p className="mt-1 text-muted">Your vocabulary, and how well each word is holding.</p>
        </div>
        <TextLink href={ADD_WORDS_HREF} className="-ml-4 sm:ml-0">
          Add words
        </TextLink>
      </header>
      {notice !== null && <Feedback tone="success">{notice}</Feedback>}
      {listError !== null && (
        <Feedback tone="error" role="alert">
          {listError}
        </Feedback>
      )}
      {tagsError !== null && (
        <Feedback tone="error" role="alert">
          {tagsError}
        </Feedback>
      )}
      {list === null ? (
        listError === null && <p className="text-center text-muted">Loading words...</p>
      ) : (
        <>
          <SummaryTiles summary={list.summary} />
          {tags.length > 0 && (
            <Field
              label="Tag"
              as="select"
              value={tag ?? ALL_TAGS}
              onChange={(event) => setTag(event.target.value === ALL_TAGS ? null : event.target.value)}
            >
              <option value={ALL_TAGS}>All tags</option>
              {tags.map(({ tag: name, count }) => (
                <option key={name} value={name}>
                  {name} ({count})
                </option>
              ))}
            </Field>
          )}
          {list.words.length === 0 ? (
            <EmptyState tag={tag} />
          ) : (
            <ul className="flex flex-col gap-3">
              {list.words.map((word) => (
                <li key={word.id}>
                  <WordCard word={word} now={now} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageLayout>
  )
}
