import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LocaleProvider } from './lib/i18n/context'
import { routeFor } from './lib/route'
import './index.css'

/* Route dispatch at boot is a single read of the URL. The customer-facing route
 * is entered by a 302 from FastAPI's /m/:merchantId and never changes after
 * that; the internal crawler's two paths are managed by App.tsx with pushState
 * and popstate, which is why no router is installed here. */
const route = routeFor(window.location.pathname, window.location.search)

const root = document.getElementById('root')

if (root !== null) {
  createRoot(root).render(
    // Kept on in development on purpose. Strict Mode's double-invoked effects
    // are exactly the condition that would otherwise let a duplicate generation
    // request reach production, and each one costs money and a cap slot.
    <StrictMode>
      <ErrorBoundary>
        {/* Above App, because every screen under it reads the catalogue and
          * they are spread across two levels: App renders the unavailable
          * screen itself, Reviewer renders the customer's, and the internal
          * crawler its own. One provider, so the language chosen in the drawer
          * is the same choice on either side of the tool. */}
        <LocaleProvider>
          <App route={route} />
        </LocaleProvider>
      </ErrorBoundary>
    </StrictMode>,
  )
}
