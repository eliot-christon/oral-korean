import { useEffect, useState } from 'react'

/**
 * A one-line confirmation carried across a navigation: the add page leaves "Added 2 words."
 * for the word list it opens next, which shows it once. A page that navigates away is
 * unmounted with its state, and a hash URL has no room for it, hence this one slot.
 */
let pending: string | null = null

export function leaveNotice(text: string): void {
  pending = text
}

/** The notice left for this page, if any: read once when the page mounts, then gone. */
export function useNotice(): string | null {
  const [notice] = useState(() => pending)
  useEffect(() => {
    pending = null
  }, [])
  return notice
}
