import type { KeyboardEvent } from 'react'

/**
 * Attributes for a field the user types Hangul into, phone keyboards included: marked as
 * Korean (the Hangul face, the right screen-reader voice), and with no capitalising,
 * correcting, spell-checking or autofilling, which a Latin-language keyboard would otherwise
 * apply to it.
 */
export const KOREAN_INPUT = {
  lang: 'ko',
  autoCapitalize: 'off',
  autoCorrect: 'off',
  spellCheck: false,
  autoComplete: 'off',
} as const

// What some browsers (Safari among them) report for a key pressed while an input method
// is composing, instead of setting `isComposing`.
const IME_PROCESSING_KEY_CODE = 229

/**
 * Whether this key press should submit: a fresh Enter, and never one that an input method
 * is still using. With a Korean keyboard the last syllable is still being composed when
 * Enter is pressed; submitting then would send it half-built (사ㄱ for 사과).
 */
export function isSubmitEnter(event: KeyboardEvent): boolean {
  return (
    event.key === 'Enter' &&
    !event.repeat &&
    !event.nativeEvent.isComposing &&
    event.nativeEvent.keyCode !== IME_PROCESSING_KEY_CODE
  )
}
