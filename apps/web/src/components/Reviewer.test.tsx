import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'

import { Reviewer } from './Reviewer'

/* The constraints §49 calls "easy to get wrong" — one generation ever, the
 * clipboard gesture, the draft, the redirect. Every one of them is invisible to
 * a type check and survives a careless refactor, so they are pinned here.
 */

const TOKEN = 'tok_abcdefghijklmnopqrstuvwxyz0123456789'
const GOOGLE = 'https://search.google.com/local/writereview?placeid=X'

const SESSION = {
  merchant: { name: 'Pho 37', category: 'Vietnamese Restaurant' },
  session: { expiresAt: '2099-01-01T00:00:00Z' },
  suggestions: [],
  googleReviewUrl: GOOGLE,
}

const BATCH = {
  suggestions: [
    { id: 's1', text: 'The beef pho was excellent.' },
    { id: 's2', text: 'Service was quick and friendly.' },
  ],
}

function jsonResponse(status: number, body: unknown) {
  const hasBody = status !== 204
  return new Response(hasBody ? JSON.stringify(body) : null, {
    status,
    headers: hasBody ? { 'Content-Type': 'application/json' } : {},
  })
}

/** Routes by URL so a test states only what it wants to differ. */
function stubApi(overrides: {
  session?: () => Response
  suggestions?: () => Response
} = {}) {
  const calls: string[] = []

  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)

    if (url.endsWith('/suggestions')) {
      return overrides.suggestions?.() ?? jsonResponse(201, BATCH)
    }
    if (url.endsWith('/select')) return jsonResponse(200, { selected: true })
    if (url.endsWith('/complete')) return jsonResponse(204, null)

    return overrides.session?.() ?? jsonResponse(200, SESSION)
  })

  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

function countOf(calls: string[], fragment: string) {
  return calls.filter((call) => call.includes(fragment)).length
}

let assigned: string[]

beforeEach(() => {
  sessionStorage.clear()
  assigned = []

  // jsdom throws on navigation; capturing the assignment is the assertion.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      pathname: `/r/${TOKEN}`,
      search: '',
      reload: vi.fn(),
      set href(url: string) {
        assigned.push(url)
      },
      get href() {
        return assigned[assigned.length - 1] ?? ''
      },
    },
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function mount(strict = false) {
  const tree = <Reviewer token={TOKEN} />
  render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  await screen.findByText('Pho 37')
}

describe('one generation, ever', () => {
  it('requests the first batch exactly once under StrictMode', async () => {
    const { calls } = stubApi()

    await mount(true)
    await screen.findByText(BATCH.suggestions[0]!.text)

    // The whole point: StrictMode double-invokes effects, and each generation
    // costs money and one of five cap slots.
    expect(countOf(calls, 'POST /api/review/sessions')).toBe(1)
  })

  it('ignores extra Generate More taps while one is in flight', async () => {
    const { calls } = stubApi()

    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)

    const button = screen.getByRole('button', { name: /generate more/i })
    await act(async () => {
      button.click()
      button.click()
      button.click()
    })

    // One automatic first batch plus one from the burst of taps. The guard is
    // a ref set before the first await, because state would still be a render
    // behind when the second tap lands.
    expect(countOf(calls, '/suggestions')).toBe(2)
  })
})

describe('a failed first batch is not a dead end', () => {
  it('offers retry and keeps Google reachable', async () => {
    stubApi({ suggestions: () => jsonResponse(502, { error: 'generation_unavailable' }) })

    await mount()

    await waitFor(() =>
      expect(document.querySelector('.notice__text')?.textContent).toMatch(
        /couldn't generate new suggestions/i,
      ),
    )
    expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /google/i }).length).toBeGreaterThan(0)
  })

  it('does not claim a limit was reached to somebody who saw nothing', async () => {
    stubApi({ suggestions: () => jsonResponse(429, { error: 'generation_limit_reached' }) })

    await mount()

    await waitFor(() =>
      expect(document.querySelector('.notice__text')?.textContent).toMatch(
        /couldn't prepare suggestions/i,
      ),
    )
    expect(screen.queryByText(/reached the limit/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /generate more/i })).toBeNull()
  })
})

describe('suggestions accumulate', () => {
  it('appends the new batch below the old one instead of replacing it', async () => {
    let call = 0
    stubApi({
      suggestions: () => {
        call += 1
        return jsonResponse(201, {
          suggestions: [{ id: `b${call}`, text: `Batch ${call} suggestion.` }],
        })
      },
    })

    await mount()
    await screen.findByText('Batch 1 suggestion.')

    await act(async () => {
      screen.getByRole('button', { name: /generate more/i }).click()
    })
    await screen.findByText('Batch 2 suggestion.')

    // The earlier batch is still there, and still above the newer one.
    const texts = [...document.querySelectorAll('.card__text')].map((n) => n.textContent)
    expect(texts).toEqual(['Batch 1 suggestion.', 'Batch 2 suggestion.'])
  })
})

describe('the editor', () => {
  async function selectFirst() {
    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)
    await act(async () => {
      screen.getAllByRole('button', { name: /use this review/i })[0]!.click()
    })
    return screen.getByRole('textbox') as HTMLTextAreaElement
  }

  it('never blocks Continue on an empty review', async () => {
    stubApi()
    const textarea = await selectFirst()

    fireEvent.change(textarea, { target: { value: '' } })
    expect(textarea.value).toBe('')

    // Clearing the box is how somebody says "I'll write my own". Disabling
    // Continue here strands them: this screen has no other route to Google.
    const cont = screen.getByRole('button', { name: /continue to google/i })
    expect((cont as HTMLButtonElement).disabled).toBe(false)
  })

  it('can return to the list, releasing the draft', async () => {
    stubApi()
    await selectFirst()

    expect(Object.keys(sessionStorage)).toHaveLength(1)

    await act(async () => {
      screen.getByRole('button', { name: /choose a different suggestion/i }).click()
    })

    // Otherwise the first tap on a card is irreversible for the life of the
    // tab: the draft restores on every load.
    await screen.findByText(BATCH.suggestions[1]!.text)
    expect(Object.keys(sessionStorage)).toHaveLength(0)
  })

  it('restores the draft on remount instead of regenerating', async () => {
    const first = stubApi()
    const textarea = await selectFirst()

    fireEvent.change(textarea, { target: { value: 'My own words entirely.' } })
    expect(textarea.value).toBe('My own words entirely.')

    cleanup()
    const second = stubApi()
    render(<Reviewer token={TOKEN} />)

    await waitFor(() => {
      expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(
        'My own words entirely.',
      )
    })
    // A customer back from Google already has a review; spending a cap slot to
    // regenerate suggestions they will never see is pure waste.
    expect(countOf(second.calls, '/suggestions')).toBe(0)
    expect(countOf(first.calls, '/suggestions')).toBe(1)
  })
})

describe('continue to Google', () => {
  it('copies, fires completion without awaiting, and navigates', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const { calls } = stubApi()

    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)
    await act(async () => {
      screen.getAllByRole('button', { name: /use this review/i })[0]!.click()
    })
    await act(async () => {
      screen.getByRole('button', { name: /continue to google/i }).click()
    })

    expect(writeText).toHaveBeenCalledWith(BATCH.suggestions[0]!.text)
    expect(countOf(calls, '/complete')).toBe(1)
    expect(assigned).toEqual([GOOGLE])
  })

  it('still reaches Google when the clipboard is unavailable', async () => {
    // The insecure-context case: navigator.clipboard is undefined, not a
    // rejecting promise. R9c makes this silent.
    vi.stubGlobal('navigator', { ...navigator, clipboard: undefined })
    stubApi()

    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)
    await act(async () => {
      screen.getAllByRole('button', { name: /use this review/i })[0]!.click()
    })
    await act(async () => {
      screen.getByRole('button', { name: /continue to google/i }).click()
    })

    expect(assigned).toEqual([GOOGLE])
  })

  it('navigates once however many times it is tapped', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn() } })
    const { calls } = stubApi()

    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)
    await act(async () => {
      screen.getAllByRole('button', { name: /use this review/i })[0]!.click()
    })

    const cont = screen.getByRole('button', { name: /continue to google/i })
    await act(async () => {
      cont.click()
      cont.click()
      cont.click()
    })

    // A second completion would double-count the funnel's last step.
    expect(countOf(calls, '/complete')).toBe(1)
    expect(assigned).toEqual([GOOGLE])
  })

  it('skips without touching the clipboard when no suggestion was chosen', async () => {
    const writeText = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    stubApi()

    await mount()
    await screen.findByText(BATCH.suggestions[0]!.text)
    await act(async () => {
      screen.getByRole('button', { name: /continue to google →/i }).click()
    })

    expect(writeText).not.toHaveBeenCalled()
    expect(assigned).toEqual([GOOGLE])
  })
})

describe('a dead token is terminal wherever it surfaces', () => {
  it('shows the rescan advice when the session load 410s', async () => {
    stubApi({ session: () => jsonResponse(410, { error: 'session_unavailable' }) })
    render(<Reviewer token={TOKEN} />)

    await screen.findByText(/this review session is no longer available/i)
    // Never the cause, and never the merchant.
    expect(screen.queryByText(/Pho 37/)).toBeNull()
  })

  it('refuses a destination that is not https', async () => {
    stubApi({
      session: () =>
        jsonResponse(200, { ...SESSION, googleReviewUrl: "javascript:alert('x')" }),
    })
    render(<Reviewer token={TOKEN} />)

    await screen.findByText(/no longer available/i)
    expect(assigned).toEqual([])
  })
})

describe('announcements', () => {
  it('mounts the live region before there is anything to announce', async () => {
    stubApi({ session: () => jsonResponse(200, SESSION) })
    render(<Reviewer token={TOKEN} />)

    // Present during loading, i.e. before the first message. A live region
    // inserted together with its text is usually not announced at all.
    const region = document.querySelector('[role="status"][aria-live="polite"]')
    expect(region).not.toBeNull()
    expect(region?.textContent).toBe('')

    await screen.findByText(BATCH.suggestions[0]!.text)
    expect(document.querySelector('[aria-live="polite"]')?.textContent).toMatch(
      /suggestions ready/i,
    )
  })
})
