// @vitest-environment node
//
// Node, not jsdom: importing vite.config.ts loads esbuild, which refuses to
// run against jsdom's TextEncoder.

import { describe, expect, it } from 'vitest'

import viteConfig from '../../vite.config'

/* The dev server and nginx split the same URL space. A prefix one of them
 * proxies to FastAPI and the other serves as the SPA is a path that works in
 * development and dead-ends in production. */

describe('the dev server proxies exactly what nginx proxies', () => {
  it('anchors every proxied prefix, as nginx does', () => {
    const proxy = (viteConfig as { server?: { proxy?: Record<string, unknown> } }).server
      ?.proxy

    // A bare '/api' also matches /apifoo; nginx's `~ ^/api(/|$)` does not.
    expect(Object.keys(proxy ?? {})).toEqual(['^/api(/|$)', '^/m(/|$)'])
  })
})
