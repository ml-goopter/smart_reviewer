/* Two static paths and one parameter.
 *
 * No router library: both routes are entered by a server-side 302 from
 * /m/:merchantId, and everything after that — suggestions, editor — is state at
 * a fixed URL. There is no in-app navigation for a router to manage.
 */

export type Route =
  | { name: 'reviewer'; token: string }
  /** `busy` is the per-IP creation limit, which clears on its own. Every other
   *  cause is permanent as far as the customer is concerned. */
  | { name: 'unavailable'; reason: 'link' | 'busy' }

export function routeFor(pathname: string, search = ''): Route {
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
