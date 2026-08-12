import { act, cleanup, fireEvent, render as renderBare, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'

import { LocaleProvider } from '../../lib/i18n/context'

import { ContextEditor } from './ContextEditor'
import { CopyButton } from './CopyButton'
import { LeadCrawler } from './LeadCrawler'
import type { LeadSearchResponse } from '../../lib/leadTypes'

/* Every screen here reads the catalogue, so every render needs the provider.
 * Pinned to English: these tests assert the English wording, and the drawer's
 * own behaviour is TopBar.test.tsx's subject. `localised.test.tsx` is what
 * proves the crawler holds no literal. */
function render(element: ReactElement) {
  return renderBare(<LocaleProvider initial="en">{element}</LocaleProvider>)
}

/* The parts of the crawler that are easy to get wrong and invisible to a type
 * check: the funnel that keeps a short list legible, the criteria that must not
 * be sent as empty strings, the save that carries only a Place ID, and the two
 * failures an operator can actually act on.
 */

const CATEGORIES = { categories: [{ value: 'restaurant', label: 'Restaurant' }] }

const SAVED_MERCHANT = {
  id: 'e2b1f6a4-0f6d-4a2e-9c3e-0d3d9a1f0c11',
  name: 'Sushi Mura',
  slug: 'sushi-mura-richmond',
  subscription: {
    status: 'ACTIVE' as const,
    expiresAt: '2026-09-12T07:00:00Z',
    lastValidDay: '2026-09-11',
    duration: 30,
    durationUnit: 'day',
  },
  url: 'https://reviews.example.test/m/e2b1f6a4-0f6d-4a2e-9c3e-0d3d9a1f0c11',
  category: null,
  address: null,
  city: null,
  website: null,
  googlePlaceId: 'ChIJsushi',
  googleRating: null,
  googleReviewCount: null,
  googleSyncedAt: null,
  createdAt: '2026-08-10T00:00:00Z',
}

function result(overrides: Partial<LeadSearchResponse['results'][number]> = {}) {
  return {
    placeId: 'ChIJsushi',
    name: 'Sushi Mura',
    category: 'Sushi Restaurant',
    address: '120 No 3 Rd',
    distanceMeters: 1200,
    rating: 4.2,
    reviewCount: 187,
    phone: null,
    website: null,
    saved: false,
    merchantId: null,
    subscription: null,
    url: null,
    ...overrides,
  }
}

function response(overrides: Partial<LeadSearchResponse> = {}): LeadSearchResponse {
  return {
    resolvedLocation: {
      query: 'V6X 1T3',
      formatted: 'Richmond, BC V6X 1T3, Canada',
      lat: 49.17,
      lng: -123.13,
    },
    searched: 60,
    matched: 1,
    partial: false,
    truncated: false,
    results: [result()],
    ...overrides,
  }
}

function reply(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  } as Response)
}

/** A response the test decides when to deliver — the only way to observe two
 *  requests being in flight at the same moment. */
function deferred() {
  let deliver!: (body: unknown, status?: number) => void
  const promise = new Promise<Response>((resolve) => {
    deliver = (body, status = 200) =>
      resolve({
        ok: status < 400,
        status,
        json: () => Promise.resolve(body),
      } as Response)
  })
  return { promise, deliver }
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path.includes('/categories')) return reply(CATEGORIES)
    // The saved list is a GET on the same path save POSTs to.
    if (path.startsWith('/api/leads/merchants') && init?.method === undefined) {
      return reply({ merchants: [] })
    }
    return reply(response())
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  // Persisted between tests otherwise: jsdom keeps one sessionStorage for the
  // whole file, so a restored search would leak into the next test's panel.
  sessionStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const click = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
  })

/** The tabs are role="tab", not buttons — the Search tab and the search form's
 *  submit button would otherwise share an accessible name. */
const clickTab = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole('tab', { name }))
  })

/** One change event per character, appended to whatever the field currently
 *  shows — a keystroke sequence, not a paste. A single change carrying the
 *  finished string round-trips cleanly through any normalisation a controlled
 *  field applies on the way in, which is exactly the class of bug that hides
 *  behind it: the field is unusable to type into and the test still passes.
 *
 *  A `<select>` is set in one event: its value can only ever be an option. */
const type = async (label: string, value: string) =>
  act(async () => {
    const field = screen.getByLabelText(label)
    if (field instanceof HTMLSelectElement) {
      fireEvent.change(field, { target: { value } })
      return
    }
    const box = field as HTMLInputElement | HTMLTextAreaElement
    fireEvent.change(box, { target: { value: '' } })
    for (const character of value) {
      fireEvent.change(box, { target: { value: box.value + character } })
    }
  })

/** A search with no subject — refused in the browser. */
async function runSearch() {
  render(<LeadCrawler onEdit={() => {}} />)
  await click('Search')
}

/** A search the form will actually send. Every request needs a text query or a
 *  category, so the shared helper supplies one. */
async function runValidSearch() {
  render(<LeadCrawler onEdit={() => {}} />)
  await screen.findByRole('option', { name: 'Restaurant' })
  await type('Text query', 'sushi')
  await click('Search')
}

function bodyOf(path: string, method?: string) {
  const call = fetchMock.mock.calls.find(
    (entry) =>
      entry[0] === path &&
      (method === undefined || (entry[1] as RequestInit | undefined)?.method === method),
  )
  return JSON.parse((call![1] as RequestInit).body as string)
}

describe('the funnel', () => {
  it('states how many listings were searched, not just how many matched', async () => {
    await runValidSearch()

    expect(await screen.findByText('60 listings searched · 1 matched')).toBeTruthy()
  })

  it('echoes the location Google resolved, so a typo is visible', async () => {
    await runValidSearch()

    expect(await screen.findByText(/Richmond, BC V6X 1T3, Canada/)).toBeTruthy()
    // Written out rather than assembled from the catalogue: the sentence is
    // split around the emphasised place so each language can put it where its
    // own word order wants it, which leaves the spacing either side
    // load-bearing and invisible to a test that reads the same two halves.
    expect(document.querySelector('.lead-resolved')?.textContent).toBe(
      'Searched around Richmond, BC V6X 1T3, Canada.',
    )
  })

  it('explains an empty list rather than leaving it blank', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(response({ matched: 0, results: [] })),
    )
    await runValidSearch()

    expect(
      await screen.findByText(/rating and review-count limits are applied after/),
    ).toBeTruthy()
  })

  it('warns when the results are incomplete', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(response({ partial: true, searched: 20 })),
    )
    await runValidSearch()

    expect(await screen.findByText(/results are incomplete/)).toBeTruthy()
  })

  it('warns when the search stopped at the result ceiling', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(response({ truncated: true })),
    )
    await runValidSearch()

    expect(await screen.findByText(/Stopped at the result ceiling/)).toBeTruthy()
  })
})

describe('criteria', () => {
  it('omits blank fields rather than sending empty strings', async () => {
    await runValidSearch()

    expect(bodyOf('/api/leads/search')).toEqual({
      // Whatever the form is seeded with; the subject here is the six criteria
      // that are absent, not which city the panel opens on.
      location: (screen.getByLabelText('Location') as HTMLInputElement).value,
      radiusMeters: 5000,
      textQuery: 'sushi',
    })
  })

  it('refuses a location with nothing to look for, without calling the API', async () => {
    // searchText rejects an empty textQuery, and the geocode behind it is
    // billed — so this refusal never leaves the browser.
    await runSearch()

    expect(await screen.findByText(/does not say what to look for/)).toBeTruthy()
    expect(
      fetchMock.mock.calls.filter((call) => call[0] === '/api/leads/search'),
    ).toHaveLength(0)
  })

  it('falls back to the default radius when the field is emptied', async () => {
    render(<LeadCrawler onEdit={() => {}} />)
    await screen.findByRole('option', { name: 'Restaurant' })
    await type('Text query', 'sushi')
    await type('Radius (m)', '')

    await click('Search')

    // `Number('')` is 0, which the API rejects with `ge=1` — and the 0 is
    // persisted, so the form comes back already broken.
    expect(bodyOf('/api/leads/search').radiusMeters).toBe(5000)
  })

  it('caps the text query at the length the API accepts', async () => {
    render(<LeadCrawler onEdit={() => {}} />)

    // Asserted as an attribute, not by typing: jsdom does not enforce
    // maxLength on a programmatic value, so a typed 201st character would
    // land here and pass whatever the browser actually does.
    expect(screen.getByLabelText('Text query').getAttribute('maxlength')).toBe('200')
  })

  it('accepts a category alone as the subject', async () => {
    render(<LeadCrawler onEdit={() => {}} />)
    await screen.findByRole('option', { name: 'Restaurant' })

    await type('Category', 'restaurant')
    await click('Search')

    expect(bodyOf('/api/leads/search').category).toBe('restaurant')
  })

  it('states the requirement before it is hit', async () => {
    render(<LeadCrawler onEdit={() => {}} />)

    expect(screen.getByText(/A category or a text query is required/)).toBeTruthy()
  })

  it('sends what was typed', async () => {
    render(<LeadCrawler onEdit={() => {}} />)
    await screen.findByRole('option', { name: 'Restaurant' })

    await type('Text query', 'Sushi Mura')
    await type('Max reviews', '200')
    await type('Category', 'restaurant')
    await click('Search')

    const body = bodyOf('/api/leads/search')
    expect(body.textQuery).toBe('Sushi Mura')
    expect(body.maxReviewCount).toBe(200)
    expect(body.category).toBe('restaurant')
  })

  it('takes the category list from the server rather than the bundle', async () => {
    render(<LeadCrawler onEdit={() => {}} />)

    expect(await screen.findByRole('option', { name: 'Restaurant' })).toBeTruthy()
  })
})

describe('failures', () => {
  it('says a location was not recognised instead of showing no results', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ error: 'location_not_found' }, 400),
    )
    await runValidSearch()

    expect(await screen.findByText(/does not recognise that location/)).toBeTruthy()
  })

  it('announces a failed search rather than only showing it', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ error: 'location_not_found' }, 400),
    )
    await runValidSearch()

    const failure = await screen.findByText(/does not recognise that location/)
    // A screen-reader user whose search fails otherwise gets nothing at all.
    expect(failure.closest('[aria-live]')).not.toBeNull()
  })

  it('does not put Google’s own message on the screen', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ error: 'provider_unavailable' }, 502),
    )
    await runValidSearch()

    expect(await screen.findByText(/Google did not answer/)).toBeTruthy()
  })
})

describe('saving', () => {
  async function saveFirstRow() {
    await runValidSearch()
    await screen.findByText('Sushi Mura')

    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ created: true, note: null, merchant: SAVED_MERCHANT }),
    )
    await click('Save')
  }

  it('sends only the place id', async () => {
    await saveFirstRow()

    await waitFor(() => {
      expect(bodyOf('/api/leads/merchants')).toEqual({ placeId: 'ChIJsushi' })
    })
  })

  it('turns the row into a copyable URL without a second search', async () => {
    await runValidSearch()
    await screen.findByText('Sushi Mura')
    const before = fetchMock.mock.calls.filter(
      (call) => call[0] === '/api/leads/search',
    ).length

    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ created: true, note: null, merchant: SAVED_MERCHANT }),
    )
    await click('Save')

    expect(await screen.findByRole('button', { name: 'Copy URL' })).toBeTruthy()
    // Re-running the search would be a second bill, and would reorder the list
    // under the operator.
    expect(
      fetchMock.mock.calls.filter((call) => call[0] === '/api/leads/search').length,
    ).toBe(before)
  })

  it('keeps every save in flight marked, not just the most recent', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(
            response({
              results: [
                result({ placeId: 'ChIJa', name: 'Alpha' }),
                result({ placeId: 'ChIJb', name: 'Beta' }),
              ],
            }),
          ),
    )
    await runValidSearch()
    await screen.findByText('Beta')

    const first = deferred()
    const second = deferred()
    const pending = [first, second]
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories') ? reply(CATEGORIES) : pending.shift()!.promise,
    )

    const buttons = screen.getAllByRole('button', { name: 'Save' })
    await act(async () => {
      fireEvent.click(buttons[0]!)
    })
    await act(async () => {
      fireEvent.click(buttons[1]!)
    })
    expect(screen.getAllByRole('button', { name: 'Saving…' })).toHaveLength(2)

    await act(async () => {
      first.deliver({ created: true, note: null, merchant: SAVED_MERCHANT }, 201)
      await first.promise
    })

    // Beta's POST is still open. Re-enabling its button here is an invitation
    // to send the same save twice.
    expect(screen.getAllByRole('button', { name: 'Saving…' })).toHaveLength(1)
    void second
  })

  it('says when the save found a row that already existed', async () => {
    await runValidSearch()
    await screen.findByText('Sushi Mura')

    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ created: false, note: null, merchant: SAVED_MERCHANT }),
    )
    await click('Save')

    expect(await screen.findByText(/was already saved/)).toBeTruthy()
  })

  it('warns in its own words that an archived URL will not open', async () => {
    await runValidSearch()
    await screen.findByText('Sushi Mura')

    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({
            created: true,
            merchant: { ...SAVED_MERCHANT, subscription: null },
          }),
    )
    await click('Save')

    // The normal outcome of a save: the row exists, the URL exists, and
    // neither opens until somebody subscribes it. The sentence is built here
    // rather than echoed from the API, which sends no prose — one from the
    // server would be an English line under a Chinese header.
    expect(
      await screen.findByText(/not subscribed — this URL will not open until it is/),
    ).toBeTruthy()
  })

  it('marks a saved but unsubscribed row, and still offers its URL', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(
            response({
              results: [
                result({
                  saved: true,
                  merchantId: 'x',
                  subscription: null,
                  url: 'https://reviews.example.test/m/x',
                }),
              ],
            }),
          ),
    )
    await runValidSearch()

    // The URL is derived from the merchant id and always exists; whether it
    // opens is the subscription's answer, shown beside it.
    expect(await screen.findByText('not subscribed')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Copy URL' })).toBeTruthy()
  })
})

describe('what a result carries', () => {
  it('shows the phone and website, which is what a prospector acts on', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(
            response({
              results: [
                result({ phone: '+1 604-555-0100', website: 'https://sushimura.test' }),
              ],
            }),
          ),
    )
    await runValidSearch()
    await screen.findByText('Sushi Mura')

    expect(screen.getByText(/604-555-0100/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Website' }).getAttribute('href')).toBe(
      'https://sushimura.test',
    )
  })

  it('does not claim a review count Google did not give', async () => {
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply(response({ results: [result({ reviewCount: null })] })),
    )
    await runValidSearch()
    await screen.findByText('Sushi Mura')

    // "0" would assert a fact the API explicitly marked unknown, and the
    // review-count cap is the filter this tool is used for.
    expect(screen.getByText('—')).toBeTruthy()
    expect(screen.queryByText('0')).toBeNull()
  })
})

describe('the saved list', () => {
  const page = (count: number, offset = 0) => ({
    merchants: Array.from({ length: count }, (_, index) => ({
      ...SAVED_MERCHANT,
      id: `merchant-${offset + index}`,
      name: `Merchant ${offset + index}`,
    })),
  })

  function listing(first: number, rest: number) {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.includes('/categories')) return reply(CATEGORIES)
      if (init?.method === undefined) {
        return reply(path.includes('offset=50') ? page(rest, 50) : page(first))
      }
      return reply(response())
    })
  }

  it('shows the subscription but does not let a row change it', async () => {
    listing(1, 0)
    render(<LeadCrawler onEdit={() => {}} />)
    await clickTab('Saved')
    await screen.findByText('Merchant 0')

    // The state is worth seeing at a glance — it is the only place a lapsing
    // subscription becomes visible at all.
    expect(screen.getByText('ACTIVE')).toBeTruthy()
    // Day, month and year, ordered by the locale rather than by us — asserting a
    // literal string here would pin en-US's ordering as if it were the format.
    expect(screen.getByText(/Expires\b.*\b11\b.*2026/)).toBeTruthy()

    // Acting on it belongs to the merchant's own page.
    expect(screen.queryByRole('button', { name: /Renew/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
  })

  it('reaches merchants past the first page', async () => {
    listing(50, 1)
    render(<LeadCrawler onEdit={() => {}} />)
    await clickTab('Saved')
    await screen.findByText('Merchant 0')

    await click('Load more')

    expect(await screen.findByText('Merchant 50')).toBeTruthy()
    // Appended, not replaced: the first page is still the operator's list.
    expect(screen.getByText('Merchant 0')).toBeTruthy()
  })

  it('announces a failure rather than only showing it', async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : init?.method === undefined
          ? reply({}, 500)
          : reply(response()),
    )
    render(<LeadCrawler onEdit={() => {}} />)
    await clickTab('Saved')

    const failure = await screen.findByText('Could not load saved merchants.')
    expect(failure.getAttribute('role')).toBe('alert')
  })

  it('offers nothing more once a page comes back short', async () => {
    listing(2, 0)
    render(<LeadCrawler onEdit={() => {}} />)
    await clickTab('Saved')
    await screen.findByText('Merchant 0')

    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })
})

describe('the tabs', () => {
  it('completes the pattern the role announces', async () => {
    render(<LeadCrawler onEdit={() => {}} />)

    const search = screen.getByRole('tab', { name: 'Search' })
    const panel = screen.getByRole('tabpanel')
    expect(search.getAttribute('aria-controls')).toBe(panel.id)
    expect(panel.getAttribute('aria-labelledby')).toBe(search.id)
    // Roving tabindex: Tab leaves the tablist rather than stepping through it.
    expect(screen.getByRole('tab', { name: 'Saved' }).getAttribute('tabindex')).toBe('-1')

    await act(async () => {
      fireEvent.keyDown(search, { key: 'ArrowRight' })
    })

    expect(screen.getByRole('tab', { name: 'Saved' }).getAttribute('aria-selected')).toBe(
      'true',
    )
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(
      'lead-tab-saved',
    )
  })
})

describe('the copy button', () => {
  it('restarts the confirmation on a second copy', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('navigator', {
        ...navigator,
        clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
      })
      render(<CopyButton url="https://reviews.example.test/m/1" />)

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
      })
      // The label changed on the button the operator just pressed, which a
      // screen reader does not re-announce on its own.
      expect(screen.getByText('Copied to clipboard').getAttribute('aria-live')).toBe(
        'polite',
      )

      await act(async () => {
        vi.advanceTimersByTime(1900)
      })
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Copied' }))
      })
      await act(async () => {
        vi.advanceTimersByTime(200)
      })

      // The first click's timer must not clear the second click's
      // confirmation, which reads as a copy that did not happen.
      expect(screen.getByRole('button', { name: 'Copied' })).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('the context editor', () => {
  const MERCHANT = {
    ...SAVED_MERCHANT,
    name: 'Pho 37',
    slug: 'pho-37-richmond',
    city: 'Richmond',
    googlePlaceId: 'ChIJpho',
    googleRating: 3.9,
    googleReviewCount: 64,
    googleSyncedAt: '2026-08-10T00:00:00Z',
  }

  const CONTEXT = {
    businessSummary: 'Family-run Vietnamese kitchen.',
    products: ['beef pho', 'spring rolls'],
    services: null,
    menuItems: null,
    sellingPoints: null,
    approvedKeywords: null,
    experienceTopics: null,
    customInstructions: null,
  }

  const loaded = () =>
    fetchMock.mockImplementation(() => reply({ merchant: MERCHANT, context: CONTEXT }))

  /** Read the raw value: testing-library's display-value matchers normalise
   *  whitespace, so a one-per-line textarea can never be matched against a
   *  string containing newlines. */
  const valueOf = (label: string) =>
    (screen.getByLabelText(label) as HTMLTextAreaElement).value

  async function openEditor() {
    render(<ContextEditor merchantId={MERCHANT.id} onBack={() => {}} />)
    await screen.findByText('Pho 37')
  }

  // --- the subscription card ------------------------------------------------
  //
  // These controls live here rather than on the saved list: changing a
  // subscription is a deliberate act with money behind it, not something to do
  // by mis-tapping one row of a fifty-row table.

  function subscriptionReplies(subscription: unknown) {
    const calls: RequestInit[] = []
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.includes('/subscription')) {
        calls.push(init!)
        return reply({
          status: 'ACTIVE',
          expiresAt: '2026-09-12T07:00:00Z',
          lastValidDay: '2026-09-11',
          duration: 21,
          durationUnit: 'day',
        })
      }
      return reply({
        merchant: { ...MERCHANT, subscription },
        context: CONTEXT,
      })
    })
    return calls
  }

  it('renews for the default term, and says how many days that is', async () => {
    const calls = subscriptionReplies(SAVED_MERCHANT.subscription)
    await openEditor()

    await click('Renew 21 days')

    expect(calls).toHaveLength(1)
    expect(calls[0]!.method).toBe('POST')
    expect(JSON.parse(calls[0]!.body as string)).toEqual({
      duration: 21,
      durationUnit: 'day',
    })
  })

  it('offers Subscribe rather than Renew when there is no subscription', async () => {
    subscriptionReplies(null)
    await openEditor()

    expect(screen.getByRole('button', { name: 'Subscribe 21 days' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Renew/ })).toBeNull()
    // Nothing to suspend yet.
    expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull()
  })

  it('suspends through PATCH, which is a different call from renewing', async () => {
    const calls = subscriptionReplies(SAVED_MERCHANT.subscription)
    await openEditor()

    await click('Suspend')

    expect(calls[0]!.method).toBe('PATCH')
    expect(JSON.parse(calls[0]!.body as string)).toEqual({ status: 'CANCELLED' })
  })

  it('offers Resume, not Suspend, once it is cancelled', async () => {
    subscriptionReplies({
      ...SAVED_MERCHANT.subscription,
      status: 'CANCELLED',
    })
    await openEditor()

    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull()
    // Renew is still offered — a term can be extended while suspended — so the
    // note has to say that doing so will not reopen the URL.
    expect(screen.getByRole('button', { name: 'Renew 21 days' })).toBeTruthy()
    expect(screen.getByText(/only Resume reopens the URL/)).toBeTruthy()
  })

  it('loads the current values one per line', async () => {
    loaded()

    await openEditor()

    expect(valueOf('Products')).toBe('beef pho\nspring rolls')
    expect(valueOf('Business summary')).toBe('Family-run Vietnamese kitchen.')
    // A field Google cannot supply comes back empty rather than invented.
    expect(valueOf('Menu items')).toBe('')
  })

  it('keeps the spaces and the newlines that were typed', async () => {
    loaded()
    await openEditor()

    // Normalising on change feeds a trimmed value back into a controlled
    // textarea: the space is swallowed as it is typed, and Enter never takes
    // in a list field, so "one per line" means one word per field.
    await type('Business summary', 'family run kitchen')
    await type('Products', 'beef pho\ncrispy spring rolls')

    expect(valueOf('Business summary')).toBe('family run kitchen')
    expect(valueOf('Products')).toBe('beef pho\ncrispy spring rolls')
  })

  it('normalises on submit rather than on the way in', async () => {
    loaded()
    await openEditor()

    await type('Products', '  beef pho  \n\n  crispy spring rolls  \n')
    await click('Save context')

    await waitFor(() => {
      const body = bodyOf(`/api/leads/merchants/${MERCHANT.id}/context`, 'PUT')
      expect(body.products).toEqual(['beef pho', 'crispy spring rolls'])
    })
  })

  it('stops saying Saved once the text changes again', async () => {
    loaded()
    await openEditor()
    await click('Save context')
    await screen.findByRole('button', { name: 'Saved' })

    await type('Menu items', 'banh mi')

    // A button reading "Saved" over edited text says something false.
    expect(screen.getByRole('button', { name: 'Save context' })).toBeTruthy()
    expect(screen.queryByText('All eight fields replaced.')).toBeNull()
  })

  it('announces the outcome instead of only showing it', async () => {
    loaded()
    await openEditor()
    await click('Save context')

    const confirmation = await screen.findByText('All eight fields replaced.')
    // The region is mounted with the form: one inserted alongside its first
    // message is usually not announced at all.
    expect(confirmation.getAttribute('aria-live')).toBe('polite')
  })

  it('sends lists as arrays and blanks as null', async () => {
    loaded()
    await openEditor()

    await type('Business summary', '')
    await click('Save context')

    await waitFor(() => {
      const body = bodyOf(`/api/leads/merchants/${MERCHANT.id}/context`, 'PUT')
      expect(body.products).toEqual(['beef pho', 'spring rolls'])
      expect(body.businessSummary).toBeNull()
    })
  })

  it('explains a rejected instruction in terms of what breaks', async () => {
    fetchMock.mockImplementation((_path: string, init?: RequestInit) =>
      init?.method === 'PUT'
        ? reply({ error: 'instructions_contain_url' }, 400)
        : reply({ merchant: MERCHANT, context: CONTEXT }),
    )
    await openEditor()

    await type('Custom instructions', 'mention example.com')
    await click('Save context')

    expect(await screen.findByText(/generated reviews reject URLs/)).toBeTruthy()
  })

  it('describes each field without burying the label', async () => {
    loaded()

    await openEditor()

    // The hint is a description, not part of the accessible name: wrapped
    // inside the label it would be read out in full every time focus landed on
    // the box. getByLabelText finding the field is the assertion.
    const field = screen.getByLabelText('Selling points')
    const hint = document.getElementById(field.getAttribute('aria-describedby')!)
    expect(hint!.textContent).toMatch(/true of everyone/)
  })

  it('warns on the field that can break a merchant permanently', async () => {
    loaded()

    await openEditor()

    const field = screen.getByLabelText('Custom instructions')
    const hint = document.getElementById(field.getAttribute('aria-describedby')!)
    // A link here fails output validation for every suggestion this merchant
    // ever generates, so the hint has to say so before it is typed.
    expect(hint!.textContent).toMatch(/do not/i)
    expect(hint!.textContent).toMatch(/links/)
    expect(hint!.textContent).toMatch(/validation/)
  })

  it('shows the snapshot date beside the rating', async () => {
    loaded()

    await openEditor()

    expect(screen.getByText(/3\.9 ★ · 64 reviews \(as of/)).toBeTruthy()
  })
})

describe('the search survives leaving the screen', () => {
  /* Both trips unmount the panel: Saved is a sibling, and the editor is a
     different route that unmounts the whole crawler. A search costs two to
     four billed Google requests, so losing it is not a cosmetic problem. */

  it('restores results after a trip to Saved and back', async () => {
    await runValidSearch()
    await screen.findByText('60 listings searched · 1 matched')
    const searches = () =>
      fetchMock.mock.calls.filter((call) => call[0] === '/api/leads/search').length
    const before = searches()

    await clickTab('Saved')
    await clickTab('Search')

    expect(await screen.findByText('60 listings searched · 1 matched')).toBeTruthy()
    expect(screen.getByText('Sushi Mura')).toBeTruthy()
    // Restored, not re-fetched.
    expect(searches()).toBe(before)
  })

  it('restores the criteria that produced them', async () => {
    render(<LeadCrawler onEdit={() => {}} />)
    await screen.findByRole('option', { name: 'Restaurant' })
    await type('Location', 'V5K 0A1')
    await type('Text query', 'Sushi Mura')
    await type('Category', 'restaurant')
    await click('Search')

    await clickTab('Saved')
    await clickTab('Search')

    expect((screen.getByLabelText('Location') as HTMLInputElement).value).toBe('V5K 0A1')
    expect((screen.getByLabelText('Text query') as HTMLInputElement).value).toBe('Sushi Mura')
    expect((screen.getByLabelText('Category') as HTMLSelectElement).value).toBe(
      'restaurant',
    )
  })

  it('keeps criteria that were typed but never searched', async () => {
    render(<LeadCrawler onEdit={() => {}} />)
    await screen.findByRole('option', { name: 'Restaurant' })
    await type('Text query', 'omakase')

    await clickTab('Saved')
    await clickTab('Search')

    expect((screen.getByLabelText('Text query') as HTMLInputElement).value).toBe('omakase')
  })

  it('restores a row as saved once it has been saved', async () => {
    await runValidSearch()
    await screen.findByText('Sushi Mura')
    fetchMock.mockImplementation((path: string) =>
      path.includes('/categories')
        ? reply(CATEGORIES)
        : reply({ created: true, note: null, merchant: SAVED_MERCHANT }),
    )
    await click('Save')
    await screen.findByRole('button', { name: 'Copy URL' })

    await clickTab('Saved')
    await clickTab('Search')

    // The badge is part of the result, so it has to survive with it.
    expect(await screen.findByRole('button', { name: 'Copy URL' })).toBeTruthy()
  })

  it('survives the panel being torn down entirely, as the editor does', async () => {
    await runValidSearch()
    await screen.findByText('Sushi Mura')
    cleanup()

    render(<LeadCrawler onEdit={() => {}} />)

    expect(await screen.findByText('60 listings searched · 1 matched')).toBeTruthy()
  })
})
