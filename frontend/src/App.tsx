import { useEffect, useRef, type ReactElement } from 'react'

import { BookIcon, ClockIcon, KeypadIcon, LearnIcon, ReviewIcon } from './components/icons'
import { NavBar, type NavItem } from './components/NavBar'
import { AddWordsPage } from './pages/AddWordsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { NumbersPage } from './pages/NumbersPage'
import { SessionPage } from './pages/SessionPage'
import { TimePage } from './pages/TimePage'
import { WordDetailPage } from './pages/WordDetailPage'
import { WordsPage } from './pages/WordsPage'
import { routeHref, useRoute, type PageName, type Route } from './routes'

/** Each entry is the current one on any of its `pages`: adding or reading a word is Words. */
const NAV_ENTRIES: (Omit<NavItem, 'current'> & { pages: PageName[] })[] = [
  {
    pages: ['numbers'],
    href: routeHref({ page: 'numbers' }),
    label: 'Numbers',
    icon: <KeypadIcon />,
  },
  {
    pages: ['time'],
    href: routeHref({ page: 'time' }),
    label: 'Time',
    icon: <ClockIcon />,
  },
  {
    pages: ['words', 'addWords', 'word'],
    href: routeHref({ page: 'words' }),
    label: 'Words',
    icon: <BookIcon />,
  },
  {
    pages: ['learn'],
    href: routeHref({ page: 'learn' }),
    label: 'Learn',
    icon: <LearnIcon />,
  },
  {
    pages: ['review'],
    href: routeHref({ page: 'review' }),
    label: 'Review',
    icon: <ReviewIcon />,
  },
]

// A bottom tab bar on a phone, where the thumb is; a top bar from `sm:` up.
const NAV_PLACEMENT =
  'fixed inset-x-0 bottom-0 z-10 border-t border-line/30 ' +
  'sm:sticky sm:top-0 sm:bottom-auto sm:border-t-0 sm:border-b'

// The return type makes a route with no page here a type error, not a blank screen.
function Page({ route }: { route: Route }): ReactElement {
  switch (route.page) {
    case 'numbers':
      return <NumbersPage />
    case 'time':
      return <TimePage />
    case 'words':
      return <WordsPage />
    case 'addWords':
      return <AddWordsPage />
    case 'word':
      // Keyed, so going from one word to another starts the page afresh.
      return <WordDetailPage key={route.id} id={route.id} />
    case 'learn':
    case 'review':
      // Keyed, so switching between the two starts the page afresh.
      return <SessionPage key={route.page} kind={route.page} />
    case 'notFound':
      return <NotFoundPage />
  }
}

/** The shell: the navigation, and the page the URL fragment names. */
function App() {
  const route = useRoute()
  const items = NAV_ENTRIES.map(({ pages, ...entry }) => ({
    ...entry,
    current: pages.includes(route.page),
  }))

  // A new page starts at its top: a hash with no matching element scrolls nowhere, so
  // opening a word from far down the list would land far down its page.
  const shownRoute = useRef(route)
  useEffect(() => {
    if (shownRoute.current !== route) {
      shownRoute.current = route
      window.scrollTo(0, 0)
    }
  }, [route])

  return (
    <>
      <NavBar items={items} className={NAV_PLACEMENT} />
      {/* Room under the page for the fixed tab bar on a phone. */}
      <div className="pb-20 sm:pb-0">
        <Page route={route} />
      </div>
    </>
  )
}

export default App
