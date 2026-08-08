import { Reviewer } from './components/Reviewer'
import { UnavailableState } from './components/states'
import type { Route } from './lib/route'

/** Resolved once at boot from the URL the server redirected to. Nothing here
 *  navigates, so the route never changes for the lifetime of the page. */
export function App({ route }: { route: Route }) {
  if (route.name === 'reviewer') return <Reviewer token={route.token} />

  return <UnavailableState reason={route.reason} />
}
