/* Two static paths and one parameter.
 *
 * No router library. The customer-facing route is entered by a server-side 302
 * from /m/:merchantId and stays at that URL for the life of the page; the
 * internal crawler moves between /leads and /leads/:merchantId, which App.tsx
 * pushes and reads back on popstate through this function. Two paths and one
 * listener is less than a router costs.
 */

export type Route =
  | { name: 'reviewer'; token: string }
  /** The internal lead crawler. Not linked from any customer-facing screen;
   *  reached by typing the URL. */
  | { name: 'leads' }
  | { name: 'leadEditor'; merchantId: string }
  /** `busy` is the per-IP creation limit, which clears on its own. Every other
   *  cause is permanent as far as the customer is concerned. */
  | { name: 'unavailable'; reason: 'link' | 'busy' }

/** Merchant ids are UUIDs. Matching the shape rather than `.+` keeps a typo
 *  like /leads/settings out of the editor, where it would render a form
 *  against a 404. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function routeFor(pathname: string, search = ''): Route {
  if (pathname === '/leads' || pathname === '/leads/') return { name: 'leads' }

  const lead = /^\/leads\/([^/]+)\/?$/.exec(pathname)
  if (lead && UUID.test(lead[1]!)) {
    return { name: 'leadEditor', merchantId: lead[1]! }
  }

  // `location.pathname` is percent-encoded. Session tokens are
  // `secrets.token_urlsafe`, i.e. [A-Za-z0-9_-], so nothing normally needs
  // decoding — but a token that arrives encoded must still match the one the
  // server stored, and api.ts re-encodes on the way out.
  const match = /^\/r\/(.+)$/.exec(pathname)

  if (match) {
    try {
      const token = decodeURIComponent(match[1]!)
      if (token !== '') return { name: 'reviewer', token }
    } catch {
      // A malformed escape sequence cannot be a token this server issued.
    }
  }

  // Everything else, /unavailable included, lands on the same terminal screen.
  // A 404 route would be a fourth thing to design for a case that only occurs
  // when someone edits the URL by hand.
  //
  // `?retry=1` is set by the entry redirect when the request was rate-limited.
  // It carries no information about the merchant — only about how busy the
  // network the customer is standing on happens to be.
  const retry = new URLSearchParams(search).get('retry') === '1'

  return { name: 'unavailable', reason: retry ? 'busy' : 'link' }
}
