import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'

import { FORTUNES } from '../lib/fortunes'
import { CATALOGS, LOCALES, LOCALE_NAMES } from '../lib/i18n'
import { LocaleProvider } from '../lib/i18n/context'
import { memoryStorage } from '../lib/testing/memoryStorage'
import { Reviewer } from './Reviewer'

/* The fortune above the suggestion list.
 *
 * Both rules here are invisible to a type check and both survive a careless
 * refactor. The second is the one that matters: the draw lives in Reviewer,
 * above the locale-keyed <Stage>, and moving it down into Suggestions — where
 * it would read more naturally — re-rolls it on every language change. Nothing
 * but this test would notice.
 */

const TOKEN = 'tok_abcdefghijklmnopqrstuvwxyz0123456789'
const GOOGLE = 'https://search.google.com/local/writereview?placeid=X'

/* Two draws far apart in the corpus, so a re-roll cannot coincidentally land
 * on the fortune already shown. */
const FIRST = 0.1
const SECOND = 0.9
const firstIndex = Math.floor(FIRST * FORTUNES.length)
const secondIndex = Math.floor(SECOND * FORTUNES.length)

function stubApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/suggestions')) {
        return new Response(JSON.stringify({ suggestions: [] }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      return new Response(
        JSON.stringify({
          merchant: { name: 'Pho 37', category: 'Vietnamese Restaurant' },
          session: { expiresAt: '2099-01-01T00:00:00Z' },
          suggestions: [],
          googleReviewUrl: GOOGLE,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    }),
  )
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  sessionStorage.clear()
  stubApi()

  /* The first draw is pinned; every draw after it returns a *different*
   * fortune. A second draw is the failure this file exists to catch, so the
   * stub is arranged to make one visible rather than to hide it. */
  vi.spyOn(Math, 'random').mockReturnValueOnce(FIRST).mockReturnValue(SECOND)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.lang = 'en'
})

async function mount() {
  render(
    <LocaleProvider initial="en">
      <Reviewer token={TOKEN} />
    </LocaleProvider>,
  )
  await screen.findByText('Pho 37')
}

async function switchTo(name: string) {
  fireEvent.click(document.querySelector('.menu')!)
  await act(async () => {
    fireEvent.click(screen.getByRole('menuitemradio', { name }))
  })
}

describe('the fortune block', () => {
  it('shows a fortune from the corpus, between the merchant and the review block', async () => {
    await mount()

    const merchant = screen.getByText('Pho 37')
    const fortune = screen.getByText(FORTUNES[firstIndex]!.en)
    const question = screen.getByText(CATALOGS.en.suggestions.heading)

    /* DOM order, not layout: it is what a screen reader in browse mode walks,
     * and it is the whole of the placement decision. The merchant identity
     * stays first — it is what tells the customer they scanned the right QR
     * code — and the fortune sits above the review block proper. */
    expect(
      merchant.compareDocumentPosition(fortune) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(
      fortune.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('is titled, and the title is a real heading', async () => {
    await mount()

    const title = screen.getByRole('heading', { name: CATALOGS.en.fortune.heading })
    const fortune = screen.getByText(FORTUNES[firstIndex]!.en)

    expect(
      title.compareDocumentPosition(fortune) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('is not focused — the question still is', async () => {
    await mount()

    // The title is a heading but not the focus target: the band is titled, not
    // promoted ahead of the task.
    expect(document.activeElement?.className).toBe('question')
  })

  it('translates on a language switch rather than drawing again', async () => {
    await mount()
    screen.getByText(FORTUNES[firstIndex]!.en)

    await switchTo(LOCALE_NAMES['zh-Hant'])

    // The same entry, in the new language.
    expect(screen.getByText(FORTUNES[firstIndex]!['zh-Hant'])).toBeTruthy()
    // And emphatically not the one a second draw would have produced.
    expect(screen.queryByText(FORTUNES[secondIndex]!['zh-Hant'])).toBeNull()
  })

  it('draws one fortune under Strict Mode, not two', async () => {
    /* The initialiser runs twice under Strict Mode and the stub answers
     * differently each time. React keeps the first result either way, so this
     * documents the double mount rather than guarding against it — the tests
     * above are what catch a re-draw. */
    render(
      <StrictMode>
        <LocaleProvider initial="en">
          <Reviewer token={TOKEN} />
        </LocaleProvider>
      </StrictMode>,
    )
    await screen.findByText('Pho 37')

    expect(document.querySelectorAll('.fortune').length).toBe(1)
    expect(screen.getByText(FORTUNES[firstIndex]!.en)).toBeTruthy()
  })

  it('renders in Simplified Chinese too', async () => {
    render(
      <LocaleProvider initial="zh-Hans">
        <Reviewer token={TOKEN} />
      </LocaleProvider>,
    )
    await screen.findByText('Pho 37')

    expect(screen.getByText(FORTUNES[firstIndex]!['zh-Hans'])).toBeTruthy()
  })

  it('survives the trip into the editor and back', async () => {
    /* Suggestions unmounts while the editor is open. A draw held there would
     * re-roll on the way back, which is the same fault as the language switch
     * wearing different clothes. */
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const body = url.endsWith('/suggestions')
          ? { suggestions: [{ id: 's1', text: 'The beef pho was excellent.', language: 'en' }] }
          : {
              merchant: { name: 'Pho 37', category: 'Vietnamese Restaurant' },
              session: { expiresAt: '2099-01-01T00:00:00Z' },
              suggestions: [],
              googleReviewUrl: GOOGLE,
            }

        return new Response(JSON.stringify(body), {
          status: url.endsWith('/suggestions') ? 201 : 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    await mount()
    fireEvent.click(await screen.findByRole('button', { name: /use this review/i }))

    // Gone on the editor: it must not compete with the text being written.
    expect(await screen.findByRole('textbox')).toBeTruthy()
    expect(screen.queryByText(FORTUNES[firstIndex]!.en)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /choose a different suggestion/i }))

    expect(await screen.findByText(FORTUNES[firstIndex]!.en)).toBeTruthy()
  })
})

describe('the screens that have no fortune', () => {
  /* Guarded only by where the block is mounted — inside Suggestions, below
   * Stage's early returns. Nothing in the type system stops it being hoisted up
   * beside the draw in Reviewer, which reads like a tidy-up and would put a
   * fortune on the screen that tells a customer their link is dead. */

  function stubSession(respond: () => Response) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.endsWith('/suggestions')) {
          return new Response(JSON.stringify({ suggestions: [] }), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return respond()
      }),
    )
  }

  async function mountWith(respond: () => Response, settled: () => Element | null) {
    stubSession(respond)
    render(
      <LocaleProvider initial="en">
        <Reviewer token={TOKEN} />
      </LocaleProvider>,
    )
    await waitFor(() => expect(settled()).not.toBeNull())
  }

  it('not while the session is loading', async () => {
    // Never resolves, so the spinner is the whole screen for the assertion.
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))

    render(
      <LocaleProvider initial="en">
        <Reviewer token={TOKEN} />
      </LocaleProvider>,
    )

    expect(document.querySelector('.spinner')).not.toBeNull()
    expect(document.querySelector('.fortune')).toBeNull()
  })

  it('not on a dead session', async () => {
    await mountWith(
      () => new Response(JSON.stringify({ error: 'not_found' }), { status: 404 }),
      () => screen.queryByText(CATALOGS.en.unavailable.session.message),
    )

    expect(document.querySelector('.fortune')).toBeNull()
  })

  it('not on the error screen', async () => {
    await mountWith(
      () => new Response(JSON.stringify({ error: 'server' }), { status: 500 }),
      () => screen.queryByText(CATALOGS.en.error.message),
    )

    expect(document.querySelector('.fortune')).toBeNull()
  })
})

describe('the corpus', () => {
  /* Iterated over LOCALES rather than over the entry's own keys, for the reason
   * catalogs.test.ts gives: `tsc` already rejects a missing key, but `npm test`
   * does not run `tsc`, and walking Object.values would pass an entry that has
   * only two languages by never looking for the third. */
  it.each(LOCALES)('writes every fortune in %s', (locale) => {
    for (const fortune of FORTUNES) {
      expect(fortune[locale]?.trim()).toBeTruthy()
    }
  })

  it('carries no language beyond the ones declared', () => {
    for (const fortune of FORTUNES) {
      expect(Object.keys(fortune).sort()).toEqual([...LOCALES].sort())
    }
  })

  /* Every language, not just English: two entries can share a Chinese string
   * while their English differs, and the customer sees one language at a time. */
  it.each(LOCALES)('repeats no fortune in %s', (locale) => {
    const texts = FORTUNES.map((fortune) => fortune[locale])

    expect(new Set(texts).size).toBe(texts.length)
  })
})
