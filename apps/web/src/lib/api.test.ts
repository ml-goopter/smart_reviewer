import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiFailure, completeSession, generateSuggestions, loadSession, selectSuggestion } from './api'

function respond(status: number, body: unknown = {}) {
  // 204 and 304 are forbidden a body by the Response constructor, same as by
  // the HTTP spec — /complete really does answer 204.
  const hasBody = status !== 204 && status !== 304

  return vi.fn().mockResolvedValue(
    new Response(hasBody ? JSON.stringify(body) : null, {
      status,
      headers: hasBody ? { 'Content-Type': 'application/json' } : {},
    }),
  )
}

const VALID = {
  merchant: { name: 'Pho 37', category: 'Vietnamese Restaurant' },
  session: { expiresAt: '2026-08-08T06:59:00Z' },
  suggestions: [],
  googleReviewUrl: 'https://example.test/writereview',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

async function kindOf(promise: Promise<unknown>) {
  return await promise.then(
    () => 'no-failure',
    (error: unknown) => (error instanceof ApiFailure ? error.kind : 'wrong-error-type'),
  )
}

describe('status mapping', () => {
  it.each([
    [404, 'session-gone'],
    [410, 'session-gone'],
    [429, 'rate-limited'],
    [502, 'provider-down'],
    [503, 'provider-down'],
    [500, 'server'],
    [400, 'server'],
    [409, 'server'],
  ])('%i becomes %s', async (status, kind) => {
    vi.stubGlobal('fetch', respond(status, { error: 'session_not_found' }))

    expect(await kindOf(loadSession('t'))).toBe(kind)
  })

  it('reports a rejected fetch as network, not server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    expect(await kindOf(loadSession('t'))).toBe('network')
  })
})

describe('the backend error code never escapes', () => {
  it('is absent from the thrown failure', async () => {
    vi.stubGlobal('fetch', respond(410, { error: 'session_unavailable' }))

    const error = await loadSession('t').catch((e: unknown) => e)

    // Which of expired / disabled / merchant-deactivated applied is private.
    expect(JSON.stringify(error)).not.toContain('session_unavailable')
    expect((error as Error).message).not.toContain('session_unavailable')
  })
})

describe('loadSession', () => {
  it('returns the session when googleReviewUrl is present', async () => {
    vi.stubGlobal('fetch', respond(200, VALID))

    await expect(loadSession('t')).resolves.toMatchObject({ googleReviewUrl: VALID.googleReviewUrl })
  })

  it.each([
    ['empty', ''],
    ['missing', undefined],
    ['not a string', 42],
  ])('rejects a %s googleReviewUrl rather than failing at the last tap', async (_label, url) => {
    vi.stubGlobal('fetch', respond(200, { ...VALID, googleReviewUrl: url }))

    expect(await kindOf(loadSession('t'))).toBe('session-gone')
  })

  it('percent-encodes the token into the path', async () => {
    const fetchMock = respond(200, VALID)
    vi.stubGlobal('fetch', fetchMock)

    await loadSession('a/b?c')

    expect(fetchMock.mock.calls[0]![0]).toBe('/api/review/sessions/a%2Fb%3Fc')
  })

  it('carries the languages the server reports as spent', async () => {
    vi.stubGlobal('fetch', respond(200, { ...VALID, cappedLanguages: ['en', 'zh-Hans'] }))

    await expect(loadSession('t')).resolves.toMatchObject({
      cappedLanguages: ['en', 'zh-Hans'],
    })
  })

  it.each([
    ['absent', undefined],
    ['not a list', 'en'],
  ])('substitutes an empty list for a %s cappedLanguages', async (_label, value) => {
    // Reaches `.includes` on the first render, so `undefined` here is a blank
    // screen rather than a missing feature.
    vi.stubGlobal('fetch', respond(200, { ...VALID, cappedLanguages: value }))

    await expect(loadSession('t')).resolves.toMatchObject({ cappedLanguages: [] })
  })

  it('drops a language it does not serve', async () => {
    // An unrecognised tag would sit in the list forever, hiding Generate More
    // for a language it does not name.
    vi.stubGlobal('fetch', respond(200, { ...VALID, cappedLanguages: ['en', 'klingon'] }))

    await expect(loadSession('t')).resolves.toMatchObject({ cappedLanguages: ['en'] })
  })
})

describe('generateSuggestions', () => {
  it('names the language in the body', async () => {
    const fetchMock = respond(201, {
      suggestions: [{ id: '1', text: 'x', language: 'zh-Hant' }],
    })
    vi.stubGlobal('fetch', fetchMock)

    const batch = await generateSuggestions('t', 'zh-Hant')

    expect(fetchMock.mock.calls[0]![1]).toMatchObject({
      method: 'POST',
      body: '{"language":"zh-Hant"}',
    })
    expect(batch.suggestions).toHaveLength(1)
  })

  it('drops a malformed suggestion rather than rendering undefined', async () => {
    const fetchMock = respond(201, {
      suggestions: [{ id: '1', text: 'x', language: 'en' }, { id: 2 }, null],
    })
    vi.stubGlobal('fetch', fetchMock)

    const batch = await generateSuggestions('t', 'en')

    expect(batch.suggestions).toEqual([{ id: '1', text: 'x', language: 'en' }])
  })

  it('reports the cap the batch just spent', async () => {
    vi.stubGlobal('fetch', respond(201, { suggestions: [], capReached: true }))

    await expect(generateSuggestions('t', 'en')).resolves.toMatchObject({
      capReached: true,
    })
  })

  it.each([
    ['absent', undefined],
    ['not a boolean', 'true'],
  ])('treats a %s capReached as not capped', async (_label, value) => {
    // The wrong way round costs a customer generations they still have; this
    // way round costs one 429 that is already handled.
    vi.stubGlobal('fetch', respond(201, { suggestions: [], capReached: value }))

    await expect(generateSuggestions('t', 'en')).resolves.toMatchObject({
      capReached: false,
    })
  })
})

describe('selectSuggestion', () => {
  it('sends the id as suggestionId', async () => {
    const fetchMock = respond(200, { selected: true })
    vi.stubGlobal('fetch', fetchMock)

    await selectSuggestion('t', 'abc')

    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ body: JSON.stringify({ suggestionId: 'abc' }) })
  })
})

describe('completeSession', () => {
  it('sets keepalive so the request survives the navigation', () => {
    const fetchMock = respond(204)
    vi.stubGlobal('fetch', fetchMock)

    completeSession('t', { suggestionId: 'abc', reviewCopied: true })

    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ keepalive: true })
  })

  it('returns synchronously — the redirect must not wait for it', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))

    // Would hang if this were awaited internally.
    expect(completeSession('t', { reviewCopied: false })).toBeUndefined()
  })

  it('swallows a rejection instead of surfacing an unhandled promise', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('unloaded')))

    expect(() => completeSession('t', { reviewCopied: false })).not.toThrow()
    await new Promise((resolve) => setTimeout(resolve, 0))
  })

  it('does not reject on a 4xx either — it is never inspected', async () => {
    vi.stubGlobal('fetch', respond(410))

    expect(() => completeSession('t', { reviewCopied: false })).not.toThrow()
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
})
