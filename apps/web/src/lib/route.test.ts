import { describe, expect, it } from 'vitest'
import { routeFor } from './route'

describe('routeFor', () => {
  it('reads the token from /r/:token', () => {
    expect(routeFor('/r/Ks92MxD7yP')).toEqual({ name: 'reviewer', token: 'Ks92MxD7yP' })
  })

  it('accepts the full urlsafe alphabet a token can contain', () => {
    const token = 'aZ0-_' + 'x'.repeat(38)

    expect(routeFor(`/r/${token}`)).toEqual({ name: 'reviewer', token })
  })

  it('decodes a percent-encoded token back to what the server stored', () => {
    expect(routeFor('/r/a%2Db')).toEqual({ name: 'reviewer', token: 'a-b' })
  })

  it.each([
    ['/unavailable'],
    ['/'],
    ['/r'],
    ['/r/'],
    ['/m/8e09301f-f928-43d5-9f60-d1287ab98f01'],
    ['/anything/else'],
    ['/R/uppercase-is-not-the-route'],
  ])('sends %s to the unavailable screen', (pathname) => {
    expect(routeFor(pathname)).toEqual({ name: 'unavailable', reason: 'link' })
  })

  it('does not throw on a malformed escape sequence', () => {
    expect(routeFor('/r/%E0%A4%A')).toEqual({ name: 'unavailable', reason: 'link' })
  })
})

describe('the rate-limited redirect', () => {
  it('is told apart from an unavailable merchant', () => {
    expect(routeFor('/unavailable', '?retry=1')).toEqual({
      name: 'unavailable',
      reason: 'busy',
    })
  })

  it.each([['?retry=0'], ['?retry=yes'], ['?other=1'], ['']])(
    'needs the exact flag the server sends, not %s',
    (search) => {
      expect(routeFor('/unavailable', search)).toEqual({
        name: 'unavailable',
        reason: 'link',
      })
    },
  )

  it('never turns a live session into a terminal screen', () => {
    expect(routeFor('/r/sometoken', '?retry=1')).toEqual({
      name: 'reviewer',
      token: 'sometoken',
    })
  })
})

describe('the lead crawler', () => {
  const ID = '8e09301f-f928-43d5-9f60-d1287ab98f01'

  it.each([['/leads'], ['/leads/']])('serves the crawler at %s', (pathname) => {
    expect(routeFor(pathname)).toEqual({ name: 'leads' })
  })

  it.each([[`/leads/${ID}`], [`/leads/${ID}/`]])(
    'opens the context editor at %s',
    (pathname) => {
      expect(routeFor(pathname)).toEqual({ name: 'leadEditor', merchantId: ID })
    },
  )

  it('accepts an uppercase uuid', () => {
    expect(routeFor(`/leads/${ID.toUpperCase()}`)).toEqual({
      name: 'leadEditor',
      merchantId: ID.toUpperCase(),
    })
  })

  it.each([
    ['/leads/settings'],
    ['/leads/8e09301f'],
    [`/leads/${ID}/context`],
    ['/leadsfoo'],
  ])('does not open an editor for %s', (pathname) => {
    // Anything that is not a merchant id would render a form against a 404.
    expect(routeFor(pathname)).toEqual({ name: 'unavailable', reason: 'link' })
  })

  it('leaves the reviewer route alone', () => {
    expect(routeFor('/r/leads')).toEqual({ name: 'reviewer', token: 'leads' })
  })
})
