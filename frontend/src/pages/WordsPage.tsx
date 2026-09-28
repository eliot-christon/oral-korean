import { type ReactNode, useEffect, useState } from 'react'

import {
  errorMessage,
  fetchTags,
  fetchWordList,
  type SortOrder,
  type TagCount,
  type VocabularySummary,
  type Word,
  type WordListQuery,
  type WordListResponse,
  type WordSort,
} from '../api'
import { Badge, type BadgeTone } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { Feedback } from '../components/Feedback'
import { Field } from '../components/Field'
import { ArrowDownIcon, CrossIcon } from '../components/icons'
import { TextLink } from '../components/TextLink'
import { formatDue, formatPercent, formatScore } from '../format'
import { isSubmitEnter } from '../koreanInput'
import { useNotice } from '../notice'
import { routeHref } from '../routes'
import { PageLayout } from './PageLayout'

/** What the list does with one tag. A tag with no choice is ignored. */
type TagChoice = 'include' | 'exclude'

// Enough tags to pick from at a glance; the search finds the others.
const SUGGESTED_TAGS = 12

interface SortField {
  field: WordSort
  label: string
  /** The direction a newly chosen field starts in: the one most often wanted. */
  first: SortOrder
  asc: string
  desc: string
}

const SORT_FIELDS: SortField[] = [
  { field: 'added', label: 'Date added', first: 'asc', asc: 'Oldest first', desc: 'Newest first' },
  { field: 'score', label: 'Score', first: 'desc', asc: 'Lowest first', desc: 'Highest first' },
  { field: 'next_review', label: 'Next review', first: 'asc', asc: 'Soonest first', desc: 'Latest first' },
  { field: 'korean', label: 'Korean', first: 'asc', asc: '가 to 하', desc: '하 to 가' },
]

function sortField(field: WordSort): SortField {
  return SORT_FIELDS.find((candidate) => candidate.field === field) ?? SORT_FIELDS[0]
}

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
            <p className="text-muted">{word.translations.join(', ')}</p>
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

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <Card className="flex flex-col items-center gap-2 text-center text-muted">
      {filtered ? (
        <p>No word matches these tags.</p>
      ) : (
        <>
          <p>No words yet.</p>
          <TextLink href={ADD_WORDS_HREF}>Add your first words</TextLink>
        </>
      )}
    </Card>
  )
}

/** Buttons of which one is on: `aria-pressed` says which, not only the colour. */
function Toggle<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: [T, string][]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map(([option, text]) => (
        <Button
          key={option}
          variant={option === value ? 'primary' : 'subtle'}
          aria-pressed={option === value}
          onClick={() => onChange(option)}
        >
          {text}
        </Button>
      ))}
    </div>
  )
}

/**
 * A tag as the cards show it, a small pill, inside a native button whose transparent box
 * keeps the tap area 44 px tall.
 */
function TagButton({
  tone,
  label,
  onClick,
  children,
}: {
  tone: BadgeTone
  label?: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="inline-flex min-h-11 cursor-pointer items-center rounded-full focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      <Badge tone={tone}>{children}</Badge>
    </button>
  )
}

function ChosenTags({
  tags,
  tone,
  onRemove,
}: {
  tags: string[]
  tone: BadgeTone
  onRemove: (tag: string) => void
}) {
  return (
    <ul className="flex flex-wrap gap-x-2">
      {tags.map((tag) => (
        <li key={tag}>
          <TagButton tone={tone} label={`Remove ${tag}`} onClick={() => onRemove(tag)}>
            {tag}
            <CrossIcon className="ml-1 size-3.5" />
          </TagButton>
        </li>
      ))}
    </ul>
  )
}

/**
 * Find a tag by typing, tap it to include or exclude it (the toggle says which), tap a
 * chosen tag to drop it. Once two tags are included, whether a word needs any or all.
 */
function TagFilter({
  tags,
  choices,
  onChoose,
  onClear,
  matchAll,
  onMatchAll,
}: {
  tags: TagCount[]
  choices: Record<string, TagChoice>
  onChoose: (tag: string, choice: TagChoice | null) => void
  onClear: () => void
  matchAll: boolean
  onMatchAll: (matchAll: boolean) => void
}) {
  const [search, setSearch] = useState('')
  const [mode, setMode] = useState<TagChoice>('include')
  const needle = search.trim().toLowerCase()
  const matching = tags.filter(({ tag }) => !(tag in choices) && tag.toLowerCase().includes(needle))
  const suggested = matching.slice(0, SUGGESTED_TAGS)
  const included = tags.filter(({ tag }) => choices[tag] === 'include').map(({ tag }) => tag)
  const excluded = tags.filter(({ tag }) => choices[tag] === 'exclude').map(({ tag }) => tag)

  function pick(tag: string) {
    onChoose(tag, mode)
    setSearch('')
  }

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field
          label="Search tags"
          className="min-w-0 flex-1 basis-48"
          value={search}
          autoComplete="off"
          enterKeyHint="done"
          onChange={(event) => setSearch(event.target.value)}
          onKeyDown={(event) => {
            // Enter takes the first match; not while an input method is still composing.
            if (isSubmitEnter(event) && suggested.length > 0) {
              event.preventDefault()
              pick(suggested[0].tag)
            }
          }}
        />
        <Toggle
          label="A tapped tag is"
          options={[
            ['include', 'Include'],
            ['exclude', 'Exclude'],
          ]}
          value={mode}
          onChange={setMode}
        />
      </div>
      {suggested.length > 0 ? (
        <ul aria-label="Tags" className="flex flex-wrap gap-x-2">
          {suggested.map(({ tag, count }) => (
            <li key={tag}>
              <TagButton tone="tag" onClick={() => pick(tag)}>
                {tag} ({count})
              </TagButton>
            </li>
          ))}
        </ul>
      ) : (
        needle !== '' && <p className="text-muted">No other tag contains {search.trim()}.</p>
      )}
      {matching.length > suggested.length && (
        <p className="text-sm text-muted">{matching.length - suggested.length} more: search to find them.</p>
      )}
      {included.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <p className="font-bold text-ink">Only words with</p>
            {included.length >= 2 && (
              <Toggle
                label="Match"
                options={[
                  ['any', 'any of them'],
                  ['all', 'all of them'],
                ]}
                value={matchAll ? 'all' : 'any'}
                onChange={(value) => onMatchAll(value === 'all')}
              />
            )}
          </div>
          <ChosenTags tags={included} tone="score" onRemove={(tag) => onChoose(tag, null)} />
        </div>
      )}
      {excluded.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="font-bold text-ink">Without</p>
          <ChosenTags tags={excluded} tone="highlight" onRemove={(tag) => onChoose(tag, null)} />
        </div>
      )}
      {included.length + excluded.length > 0 && (
        <Button variant="subtle" className="self-start" onClick={onClear}>
          Clear tags
        </Button>
      )}
    </Card>
  )
}

/** What the list is sorted by, and one button that turns the direction around. */
function SortControl({
  field,
  order,
  onSort,
}: {
  field: WordSort
  order: SortOrder
  onSort: (field: WordSort, order: SortOrder) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field
        label="Sort by"
        as="select"
        className="min-w-0 flex-1 basis-40"
        value={field}
        onChange={(event) => {
          const chosen = sortField(event.target.value as WordSort)
          onSort(chosen.field, chosen.first)
        }}
      >
        {SORT_FIELDS.map(({ field: value, label }) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Field>
      <Button variant="secondary" onClick={() => onSort(field, order === 'asc' ? 'desc' : 'asc')}>
        <ArrowDownIcon className={order === 'asc' ? 'size-5 rotate-180' : 'size-5'} />
        {sortField(field)[order]}
      </Button>
    </div>
  )
}

/** Every word with its score and when it is due, a summary, a filter by tags and an order. */
export function WordsPage() {
  // "Added 2 words." after a paste, "Deleted 사과." after a delete.
  const notice = useNotice()
  // The filter and the order are page state, not part of the address.
  const [choices, setChoices] = useState<Record<string, TagChoice>>({})
  const [matchAll, setMatchAll] = useState(false)
  const [sort, setSort] = useState<WordSort>('added')
  const [order, setOrder] = useState<SortOrder>('asc')
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

  const included = Object.keys(choices).filter((tag) => choices[tag] === 'include')
  const excluded = Object.keys(choices).filter((tag) => choices[tag] === 'exclude')
  const query: WordListQuery = {
    tags: included,
    // The switch shows only with two included tags; with fewer, "all" would mean "any".
    match: matchAll && included.length >= 2 ? 'all' : 'any',
    exclude: excluded,
    sort,
    order,
  }
  // The query is a new object on every render: the effect depends on its text instead.
  const queryKey = JSON.stringify(query)

  useEffect(() => {
    let cancelled = false
    fetchWordList(JSON.parse(queryKey) as WordListQuery)
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
  }, [queryKey])

  function choose(tag: string, choice: TagChoice | null) {
    setChoices((previous) => {
      const { [tag]: _previous, ...others } = previous
      return choice === null ? others : { ...others, [tag]: choice }
    })
  }

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
            <TagFilter
              tags={tags}
              choices={choices}
              onChoose={choose}
              onClear={() => setChoices({})}
              matchAll={matchAll}
              onMatchAll={setMatchAll}
            />
          )}
          <SortControl
            field={sort}
            order={order}
            onSort={(field, direction) => {
              setSort(field)
              setOrder(direction)
            }}
          />
          {list.words.length === 0 ? (
            <EmptyState filtered={included.length + excluded.length > 0} />
          ) : (
            <ul aria-label="Words" className="flex flex-col gap-3">
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
