import { Component, type ReactNode } from 'react'

import { ErrorState } from './states'

/** The last thing between an unexpected throw and a white screen.
 *
 *  §14 names a blank page as the most likely moment to lose someone, and that
 *  is exactly what React does with an uncaught render error: it unmounts the
 *  whole tree. A retry screen is worth having even for failures that should
 *  never happen, because the customer is standing in a shop with a phone and
 *  no other way to reach the review page.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    // A reload rather than a state reset: whatever produced the throw is still
    // in memory, and the session survives a fresh load — the draft is in
    // sessionStorage and the token is in the URL.
    if (this.state.failed) {
      return <ErrorState onRetry={() => window.location.reload()} />
    }

    return this.props.children
  }
}
