import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ReactElement } from 'react'

import { FORTUNES } from '../lib/fortunes'
import { CATALOGS, type Locale } from '../lib/i18n'
import { LocaleProvider } from '../lib/i18n/context'
import { FortuneBlock } from './FortuneBlock'
import { SelectedReviewEditor } from './SelectedReviewEditor'
import { GenerationNotice, SuggestionCard } from './SuggestionList'
import { ErrorState, LoadingState, UnavailableState } from './states'

/* Every customer-facing screen, rendered in each locale.
 *
 * The English tests elsewhere pass whether a component reads the catalogue or
 * still holds a literal — the catalogue's English is the same text. Only
 * rendering in another language tells the two apart, which is why a screen
 * that was missed in the swap is invisible without this.
 */

afterEach(cleanup)

const CHINESE = ['zh-Hant', 'zh-Hans'] satisfies Locale[]

function inLocale(locale: Locale, element: ReactElement) {
  render(<LocaleProvider initial={locale}>{element}</LocaleProvider>)
}

describe.each(CHINESE)('%s', (locale) => {
  const messages = CATALOGS[locale]

  it('loading', () => {
    inLocale(locale, <LoadingState />)

    expect(screen.getByText(messages.loading.text)).toBeTruthy()
    expect(screen.getByRole('status', { name: messages.loading.label })).toBeTruthy()
  })

  it.each(['link', 'session', 'busy'] as const)('unavailable: %s', (reason) => {
    inLocale(locale, <UnavailableState reason={reason} />)

    expect(screen.getByText(messages.unavailable[reason].message)).toBeTruthy()
    expect(screen.getByText(messages.unavailable[reason].advice)).toBeTruthy()
  })

  it('error', () => {
    inLocale(locale, <ErrorState onRetry={() => {}} />)

    expect(screen.getByText(messages.error.message)).toBeTruthy()
    expect(screen.getByRole('button', { name: messages.error.retry })).toBeTruthy()
  })

  it('suggestion card', () => {
    inLocale(
      locale,
      <SuggestionCard suggestion={{ id: 's1', text: '湯頭很好。', language: locale }} onSelect={() => {}} />,
    )

    expect(screen.getByRole('button', { name: messages.card.use })).toBeTruthy()
  })

  /* Not from a catalogue — the corpus is its own file — but customer-facing
   * copy all the same, and this is the sweep that catches a screen rendering
   * English under a Chinese heading. */
  it('fortune', () => {
    const fortune = FORTUNES[0]

    inLocale(locale, <FortuneBlock fortune={fortune} />)

    expect(screen.getByText(fortune[locale])).toBeTruthy()
    expect(screen.queryByText(fortune.en)).toBeNull()
  })

  it('cap notice names its own language', () => {
    inLocale(
      locale,
      <GenerationNotice
        kind="rate-limited"
        hasSuggestions
        onRetry={() => {}}
        onSkip={() => {}}
      />,
    )

    expect(screen.getByText(messages.notice.capReached)).toBeTruthy()
    // Retrying a spent cap cannot succeed, so it is still not offered.
    expect(screen.queryByRole('button', { name: messages.notice.retry })).toBeNull()
  })

  it('editor, with the copy hint for a non-empty review', () => {
    inLocale(
      locale,
      <SelectedReviewEditor
        value="湯頭很好。"
        originalText="湯頭很好。"
        leaving={false}
        onChange={() => {}}
        onReset={() => {}}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )

    expect(screen.getByText(messages.editor.heading)).toBeTruthy()
    expect(screen.getByText(messages.editor.copyHint)).toBeTruthy()
    expect(screen.getByRole('textbox', { name: messages.editor.textareaLabel })).toBeTruthy()
    expect(screen.getByRole('button', { name: messages.editor.continue })).toBeTruthy()
    expect(screen.getByRole('button', { name: messages.editor.back })).toBeTruthy()
  })

  it('editor, with the empty hint for a cleared review', () => {
    inLocale(
      locale,
      <SelectedReviewEditor
        value="   "
        originalText="湯頭很好。"
        leaving={false}
        onChange={() => {}}
        onReset={() => {}}
        onBack={() => {}}
        onContinue={() => {}}
      />,
    )

    expect(screen.getByText(messages.editor.emptyHint)).toBeTruthy()
  })
})
