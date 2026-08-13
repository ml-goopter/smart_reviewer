import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { LocaleProvider } from './lib/i18n/context'

/* The only in-app navigation the product has: the crawler's list and a
 * merchant's editor. It is history, so the browser's Back button is part of the
 * contract. */

const ID = 'e2b1f6a4-0f6d-4a2e-9c3e-0d3d9a1f0c11'

const MERCHANT = {
  id: ID,
  name: 'Pho 37',
  slug: 'pho-37-richmond',
  subscription: {
    status: 'ACTIVE',
    expiresAt: '2026-09-12T07:00:00Z',
    lastValidDay: '2026-09-11',
    duration: 30,
    durationUnit: 'day',
  },
  url: `https://reviews.example.test/m/${ID}`,
  category: null,
  address: null,
  city: 'Richmond',
  website: null,
  googlePlaceId: 'ChIJpho',
  googleRating: null,
  googleReviewCount: null,
  googleSyncedAt: null,
  createdAt: '2026-08-10T00:00:00Z',
}

const CONTEXT = {
  businessSummary: null,
  products: null,
  services: null,
  menuItems: null,
  sellingPoints: null,
  approvedKeywords: null,
  experienceTopics: null,
  customInstructions: null,
}

function reply(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response)
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string) => {
      if (path.includes('/categories')) return reply({ categories: [] })
      if (path.includes('/context')) return reply({ merchant: MERCHANT, context: CONTEXT })
      return reply({ merchants: [MERCHANT] })
    }),
  )
  window.history.replaceState(null, '', '/leads')
})

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** One trip into a merchant's editor and back out of it. */
async function roundTrip() {
  await act(async () => {
    fireEvent.click(screen.getByRole('tab', { name: 'Saved' }))
  })
  await screen.findByRole('button', { name: 'Edit' })

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
  })
  await screen.findByText('Pho 37')
  expect(window.location.pathname).toBe(`/leads/${ID}`)

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '← Back' }))
    // history.back() is asynchronous in the browser and in jsdom: popstate
    // arrives on a later task.
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await waitFor(() => expect(window.location.pathname).toBe('/leads'))
}

describe('moving between the crawler and an editor', () => {
  it('pops the entry it pushed instead of pushing another', async () => {
    render(
      <LocaleProvider initial="en">
        <App route={{ name: 'leads' }} />
      </LocaleProvider>,
    )
    const before = window.history.length

    await roundTrip()
    await roundTrip()
    await roundTrip()

    // Pushing on the way back too would leave six entries here, and the
    // browser's Back would walk every one of them before leaving the tool.
    expect(window.history.length).toBeLessThanOrEqual(before + 1)
  })

  it('still reaches the list when the editor was opened by its URL', async () => {
    // Nothing of ours is on the stack, so back() would leave the site.
    window.history.replaceState(null, '', `/leads/${ID}`)
    render(
      <LocaleProvider initial="en">
        <App route={{ name: 'leadEditor', merchantId: ID }} />
      </LocaleProvider>,
    )
    await screen.findByText('Pho 37')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '← Back' }))
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(window.location.pathname).toBe('/leads')
    expect(screen.getByRole('tablist')).toBeTruthy()
  })
})
