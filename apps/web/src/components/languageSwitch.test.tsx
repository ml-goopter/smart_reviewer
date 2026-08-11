import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { LOCALE_NAMES } from '../lib/i18n'
import { LocaleProvider } from '../lib/i18n/context'
import { memoryStorage } from '../lib/testing/memoryStorage'
import { Reviewer } from './Reviewer'

/* What the drawer actually does to the reviewer.
 *
 * Every rule here was a decision with a cheaper alternative, and none of them
 * is visible to a type check: a language with suggestions already must not
 * spend a slot, a language without them must, and the request that goes out
 * has to name the language the customer chose rather than the one that
 * happened to be on screen when the effect was written.
 */

const TOKEN = 'tok_abcdefghijklmnopqrstuvwxyz0123456789'
const GOOGLE = 'https://search.google.com/local/writereview?placeid=X'

const ENGLISH = [
  { id: 'e1', text: 'The beef pho was excellent.', language: 'en' },
  { id: 'e2', text: 'Service was quick and friendly.', language: 'en' },
]

const TRADITIONAL = [
  { id: 't1', text: '湯頭很濃郁，份量也很足。', language: 'zh-Hant' },
]

function jsonResponse(status: number, body: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? {} : { 'Content-Type': 'application/json' },
  })
}

/** `stored` is what GET /sessions returns — every language at once, which is
 *  the whole reason a switch can be free. */
function stubApi(stored: unknown[], generate?: (language: string) => Response) {
  const posted: string[] = []

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/suggestions')) {
      const language = JSON.parse(String(init?.body ?? '{}')).language
      posted.push(language)
      return (
        generate?.(language) ??
        jsonResponse(201, { suggestions: language === 'en' ? ENGLISH : TRADITIONAL })
      )
    }
    if (url.endsWith('/select')) return jsonResponse(200, { selected: true })
    if (url.endsWith('/complete')) return jsonResponse(204, null)

    return jsonResponse(200, {
      merchant: { name: 'Pho 37', category: 'Vietnamese Restaurant' },
      session: { expiresAt: '2099-01-01T00:00:00Z' },
      suggestions: stored,
      googleReviewUrl: GOOGLE,
    })
  })

  vi.stubGlobal('fetch', fetchMock)
  return { posted, fetchMock }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  sessionStorage.clear()
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

describe('switching language', () => {
  it('shows the cached batch without generating again', async () => {
    const { posted } = stubApi([...ENGLISH, ...TRADITIONAL])
    await mount()

    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hant'])

    await screen.findByText(TRADITIONAL[0]!.text)
    // The English cards are still held, just not on screen.
    expect(screen.queryByText(ENGLISH[0]!.text)).toBeNull()
    expect(posted).toEqual([])
  })

  it('costs nothing to switch back', async () => {
    const { posted } = stubApi([...ENGLISH, ...TRADITIONAL])
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hant'])
    await screen.findByText(TRADITIONAL[0]!.text)
    await switchTo(LOCALE_NAMES.en)

    await screen.findByText(ENGLISH[0]!.text)
    expect(posted).toEqual([])
  })

  it('generates in the new language when it has nothing yet', async () => {
    const { posted } = stubApi(ENGLISH)
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hant'])

    await screen.findByText(TRADITIONAL[0]!.text)
    expect(posted).toEqual(['zh-Hant'])
  })

  it('asks only once per language, however often it is revisited', async () => {
    const { posted } = stubApi(ENGLISH)
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hant'])
    await screen.findByText(TRADITIONAL[0]!.text)
    await switchTo(LOCALE_NAMES.en)
    await switchTo(LOCALE_NAMES['zh-Hant'])

    await screen.findByText(TRADITIONAL[0]!.text)
    expect(posted).toEqual(['zh-Hant'])
  })

  it('generates on first load in the detected language, not in English', async () => {
    const { posted } = stubApi([])
    render(
      <LocaleProvider initial="zh-Hant">
        <Reviewer token={TOKEN} />
      </LocaleProvider>,
    )
    await screen.findByText('Pho 37')

    await screen.findByText(TRADITIONAL[0]!.text)
    expect(posted).toEqual(['zh-Hant'])
  })

  it('drops the draft and returns to the list', async () => {
    // The decision on record: switching mid-edit discards typed text.
    const { posted } = stubApi([...ENGLISH, ...TRADITIONAL])
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    fireEvent.click(screen.getAllByRole('button', { name: /use this review/i })[0]!)
    const box = (await screen.findByRole('textbox')) as HTMLTextAreaElement
    fireEvent.change(box, { target: { value: 'My own words.' } })

    await switchTo(LOCALE_NAMES['zh-Hant'])

    expect(screen.queryByRole('textbox')).toBeNull()
    await screen.findByText(TRADITIONAL[0]!.text)
    expect(posted).toEqual([])

    // And it does not come back when the language does.
    await switchTo(LOCALE_NAMES.en)
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('keeps a cap in one language from silencing another', async () => {
    const { posted } = stubApi(ENGLISH, (language) =>
      language === 'zh-Hant'
        ? jsonResponse(429, { error: 'generation_limit_reached' })
        : jsonResponse(201, { suggestions: ENGLISH }),
    )
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hant'])

    // Chinese is capped, so its Generate More is gone.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /產生更多建議/ })).toBeNull(),
    )

    await switchTo(LOCALE_NAMES.en)

    // English never hit a cap and keeps its button.
    expect(
      screen.getByRole('button', { name: /generate more suggestions/i }),
    ).toBeTruthy()
    expect(posted).toEqual(['zh-Hant'])
  })

  it('generates in the language chosen, not the one the tap started from', async () => {
    const { posted } = stubApi([])
    await mount()
    await screen.findByText(ENGLISH[0]!.text)

    await switchTo(LOCALE_NAMES['zh-Hans'])

    await waitFor(() => expect(posted).toEqual(['en', 'zh-Hans']))
  })
})
