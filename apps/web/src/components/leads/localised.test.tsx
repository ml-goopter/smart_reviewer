import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'

import { CATALOGS, type Locale } from '../../lib/i18n'
import { LocaleProvider } from '../../lib/i18n/context'
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
  status: 'ACTIVE',
  url: 'https://reviews.example.test/m/1',
  googleRating: 4.4,
  googleReviewCount: 128,
  googleSyncedAt: '2026-02-01T00:00:00Z',
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

function reply(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

beforeEach(() => {
  // The panels fetch on mount. Nothing here asserts on a request; the subject
  // is only which words reach the screen.
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) =>
      path.includes('/context')
        ? reply({ merchant: MERCHANT, context: CONTEXT })
        : reply({ categories: [{ value: 'restaurant', label: 'Restaurant' }] }),
    ),
  )
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

  it('leaves the merchant data in the language the merchant registered it in', async () => {
    inLocale(locale, <ContextEditor merchantId={MERCHANT.id} onBack={() => {}} />)

    await screen.findByText(MERCHANT.name)

    // Name, slug and status are data, not copy. Translating a status would
    // make the screen disagree with the database.
    expect(screen.getByText(new RegExp(MERCHANT.slug))).toBeTruthy()
    expect(screen.getByText(new RegExp(MERCHANT.status))).toBeTruthy()
  })
})
