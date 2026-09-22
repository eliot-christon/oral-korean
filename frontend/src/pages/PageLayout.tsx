import type { ReactNode } from 'react'

/**
 * A page's `<main>`: one centred, phone-width column. The numbers page predates it and keeps
 * its own copy of these classes, since its move into `pages/` changed nothing but imports.
 */
export function PageLayout({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-col gap-6 px-4 py-8 sm:py-12">
      {children}
    </main>
  )
}
