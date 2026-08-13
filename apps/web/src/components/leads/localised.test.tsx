import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'

import { CATALOGS, LOCALE_NAMES, type Locale, type Messages } from '../../lib/i18n'
import { LocaleProvider } from '../../lib/i18n/context'
import { memoryStorage } from '../../lib/testing/memoryStorage'
import { ContextEditor } from './ContextEditor'
import { LeadCrawler } from './LeadCrawler'

/* The crawler, rendered in each Chinese locale.
 *
 * The English tests in LeadCrawler.test.tsx pass whether a screen reads the
 * catalogue or still holds a literal — the catalogue's English is the same
 * text. Only rendering in another language tells the two apart, which is why a
 * field missed in the swap is invisible without this.
 */

const CHINESE = ['zh-Hant', 'zh-Hans'] satisfies Locale[]

const MERCHANT = {
  id: '9f1d2c34-5678-4abc-9def-000000000001',
  name: 'Pho 37',
  slug: 'pho-37-burnaby',
  subscription: {
    status: 'ACTIVE' as const,
    expiresAt: '2026-09-12T07:00:00Z',
    lastValidDay: '2026-09-11',
    duration: 30,
    durationUnit: 'day',
  },
  url: 'https://reviews.example.test/m/1',
  googleRating: 4.4,
  googleReviewCount: 128,
  googleSyncedAt: '2026-02-01T00:00:00Z',
  createdAt: '2026-02-10T00:00:00Z',
  city: 'Burnaby',
}

const CONTEXT = {
  businessSummary: 'Family-run Vietnamese kitchen.',
  products: ['beef pho'],
  services: null,
  menuItems: null,
  sellingPoints: null,
  approvedKeywords: null,
  experienceTopics: null,
  customInstructions: null,
}

const RESULT = {
  placeId: 'place-1',
  name: 'Sushi Mura',
  address: '4231 No 3 Rd, Richmond',
  category: null,
  rating: 4.4,
  reviewCount: 128,
  distanceMeters: 900,
  phone: '604-555-0100',
  website: 'https://sushimura.example.test',
  saved: false,
  merchantId: null,
  status: null,
  url: null,
}

const SEARCH = {
  resolvedLocation: { formatted: 'Richmond, BC', latitude: 49.1, longitude: -123.1 },
  searched: 60,
  matched: 1,
  partial: false,
  truncated: false,
  results: [RESULT],
}

function reply(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

/** Routes by path *and* method: the saved list and the save share one path, so
 *  matching either alone hands one of them the other's body. Nothing here
 *  asserts on a request — the subject is only which words reach the screen. */
function route(path: string, method?: string) {
  if (path.includes('/context')) {
    return contextFails
      ? reply({ error: 'server_error' }, 500)
      : reply({ merchant: MERCHANT, context: CONTEXT })
  }
  if (path.includes('/categories')) {
    return reply({ categories: [{ value: 'restaurant', label: 'Restaurant' }] })
  }
  if (path.includes('/search')) return reply(SEARCH)
  if (path.includes('/merchants') && method === 'POST') {
    // A saved row that nobody has subscribed: its URL will not open yet.
    return reply({
      created: false,
      merchant: { ...MERCHANT, subscription: null },
    })
  }
  return reply({ merchants: [MERCHANT] })
}

let failure: string | null = null

/** Every search from here on comes back as this API error code. */
function failSearch(code: string) {
  failure = code
}

let contextFails = false

/** The merchant fetch comes back 500. */
function failContext() {
  contextFails = true
}

/** A search needs a subject or the panel refuses it without calling the API,
 *  which would leave every assertion below testing the refusal instead. */
function runSearch(search: Messages['leads']['search']) {
  fireEvent.change(screen.getByLabelText(search.textQuery), {
    target: { value: 'sushi' },
  })
  fireEvent.click(screen.getByRole('button', { name: search.submit }))
}

beforeEach(() => {
  failure = null
  contextFails = false
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init?: RequestInit) => {
      if (failure !== null && init?.method === 'POST' && path.includes('/search')) {
        return reply({ error: failure }, 400)
      }
      return route(path, init?.method)
    }),
  )
  vi.stubGlobal('navigator', { clipboard: { writeText: () => Promise.resolve() } })
  // The drawer persists the language it is given, and jsdom keeps one storage
  // for the whole file — a switch here would otherwise decide the next test's
  // language.
  vi.stubGlobal('localStorage', memoryStorage())
  sessionStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function inLocale(locale: Locale, element: ReactElement) {
  render(<LocaleProvider initial={locale}>{element}</LocaleProvider>)
}

describe.each(CHINESE)('%s', (locale) => {
  const { leads } = CATALOGS[locale]

  it('names the tool and its tabs', () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    expect(screen.getByRole('heading', { name: leads.title })).toBeTruthy()
    expect(screen.getByRole('tab', { name: leads.tabs.search })).toBeTruthy()
    expect(screen.getByRole('tab', { name: leads.tabs.saved })).toBeTruthy()
    expect(screen.getByRole('tablist', { name: leads.viewsLabel })).toBeTruthy()
  })

  it('carries the same drawer the customer screens do', () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    // The one way to change language, and the reason the crawler needs no
    // switcher of its own.
    expect(screen.getByRole('button', { name: CATALOGS[locale].menu.open })).toBeTruthy()
  })

  it('labels the search form', () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    const { search } = leads
    for (const label of [
      search.location,
      search.radius,
      search.category,
      search.textQuery,
      search.ratingMin,
      search.ratingMax,
      search.maxReviews,
    ]) {
      expect(screen.getByText(label)).toBeTruthy()
    }

    expect(screen.getByRole('button', { name: search.submit })).toBeTruthy()
    expect(screen.getByText(search.note)).toBeTruthy()
  })

  it('translates a category the server sent in English', async () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    // The server is the authority on which categories exist; the words the
    // operator reads are not its business.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: leads.categories.restaurant })).toBeTruthy(),
    )
    expect(screen.getByRole('option', { name: leads.search.anyCategory })).toBeTruthy()
  })

  it('labels the editor and every field in it', async () => {
    inLocale(locale, <ContextEditor merchantId={MERCHANT.id} onBack={() => {}} />)

    await screen.findByText(MERCHANT.name)

    const { editor } = leads
    expect(screen.getByRole('button', { name: editor.back })).toBeTruthy()
    expect(screen.getByRole('button', { name: editor.save })).toBeTruthy()
    expect(screen.getByText(editor.note)).toBeTruthy()
    expect(screen.getByRole('heading', { name: editor.about })).toBeTruthy()
    expect(screen.getByRole('heading', { name: editor.offers.title })).toBeTruthy()
    expect(screen.getByRole('heading', { name: editor.voice.title })).toBeTruthy()
    expect(screen.getByRole('heading', { name: editor.instruction.title })).toBeTruthy()

    for (const field of Object.values(editor.fields)) {
      expect(screen.getByLabelText(field.label)).toBeTruthy()
    }
  })

  it('translates the results table and its actions', async () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    runSearch(leads.search)

    const { search } = leads
    await waitFor(() => expect(screen.getByText(search.merchant)).toBeTruthy())

    for (const text of [search.rating, search.reviews, search.distance]) {
      expect(screen.getByText(text)).toBeTruthy()
    }
    // The funnel and the row's own words.
    expect(screen.getByText(search.funnel(60, 1))).toBeTruthy()
    // The whole resolved sentence, not just the place inside it: the two
    // halves carry load-bearing spacing that nothing else would catch.
    // Read off the paragraph rather than matched as one node: the place sits
    // in its own <strong>, which is the emphasis being asserted.
    expect(document.querySelector('.lead-resolved')?.textContent).toBe(
      `${search.resolvedBefore}${SEARCH.resolvedLocation.formatted}${search.resolvedAfter}`,
    )
    expect(document.querySelector('.lead-resolved strong')?.textContent).toBe(
      SEARCH.resolvedLocation.formatted,
    )
    // The distance cell, which is under a translated heading.
    expect(screen.getByText(search.metres(RESULT.distanceMeters))).toBeTruthy()
    expect(screen.getByText(new RegExp(search.uncategorised))).toBeTruthy()
    expect(screen.getByRole('link', { name: search.website })).toBeTruthy()
    expect(screen.getByRole('button', { name: search.save })).toBeTruthy()

    // Data, not copy: translating a merchant's name or its address would make
    // the screen disagree with Google.
    expect(screen.getByText(RESULT.name)).toBeTruthy()
  })

  it('translates a failed search rather than leaving the API to word it', async () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    failSearch('location_not_found')
    runSearch(leads.search)

    await waitFor(() =>
      expect(screen.getByText(leads.failures.location_not_found)).toBeTruthy(),
    )
  })

  it('keeps a message in the language on screen when the language changes', async () => {
    // The message is put on screen in one language and read in another. Held
    // as a rendered sentence it would still be sitting there in the first.
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    failSearch('location_not_found')
    runSearch(leads.search)
    await waitFor(() =>
      expect(screen.getByText(leads.failures.location_not_found)).toBeTruthy(),
    )

    // Through the drawer, which is the only way it happens for real.
    fireEvent.click(document.querySelector('.menu')!)
    await act(async () => {
      fireEvent.click(screen.getByRole('menuitemradio', { name: LOCALE_NAMES.en }))
    })

    expect(screen.getByText(CATALOGS.en.leads.failures.location_not_found)).toBeTruthy()
    expect(screen.queryByText(leads.failures.location_not_found)).toBeNull()
  })

  it('translates the saved list', async () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    fireEvent.click(screen.getByRole('tab', { name: leads.tabs.saved }))

    const { saved } = leads
    await waitFor(() => expect(screen.getByText(saved.merchant)).toBeTruthy())

    expect(screen.getByText(saved.subscription)).toBeTruthy()
    expect(screen.getByText(saved.savedOn)).toBeTruthy()
    expect(screen.getByRole('button', { name: leads.edit })).toBeTruthy()
    expect(screen.getByRole('button', { name: leads.copyUrl })).toBeTruthy()

    // A status is data. Translating it would make the screen disagree with the
    // database, and it is what the operator quotes when reporting a row.
    expect(screen.getByText(MERCHANT.subscription.status)).toBeTruthy()

    // The label beside it *is* prose, so it follows the language on screen —
    // and the date it labels is the last valid day, not the stored expiresAt,
    // which is the midnight starting the day after.
    expect(screen.getByText(new RegExp(leads.subscription.expires))).toBeTruthy()

    // The date beside it follows the language on screen, not the machine's.
    const day = new Date(MERCHANT.createdAt).toLocaleDateString(locale, {
      day: '2-digit',
      month: 'short',
    })
    expect(screen.getByText(day)).toBeTruthy()
    expect(day).not.toBe(
      new Date(MERCHANT.createdAt).toLocaleDateString('en', {
        day: '2-digit',
        month: 'short',
      }),
    )
  })

  it('words a dead URL itself rather than echoing the API', async () => {
    inLocale(locale, <LeadCrawler onEdit={() => {}} />)

    runSearch(leads.search)
    await screen.findByRole('button', { name: leads.search.save })

    fireEvent.click(screen.getByRole('button', { name: leads.search.save }))

    // The server sends no prose for this; the sentence is built here, so it
    // follows the language on screen.
    await waitFor(() =>
      expect(
        screen.getByText(leads.search.notSubscribed(MERCHANT.name)),
      ).toBeTruthy(),
    )
  })

  it('translates a merchant that will not load', async () => {
    failContext()
    inLocale(locale, <ContextEditor merchantId={MERCHANT.id} onBack={() => {}} />)

    await waitFor(() => expect(screen.getByText(leads.editor.loadFailed)).toBeTruthy())
  })

  it('translates the copy button and what it says afterwards', async () => {
    inLocale(locale, <ContextEditor merchantId={MERCHANT.id} onBack={() => {}} />)

    await screen.findByText(MERCHANT.name)

    // The editor's own copy button takes no label, so this is the catalogue's
    // default rather than one passed in.
    fireEvent.click(screen.getByRole('button', { name: leads.copy.copy }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: leads.copy.copied })).toBeTruthy(),
    )
    expect(screen.getByText(leads.copy.copiedAnnouncement)).toBeTruthy()
  })
})
