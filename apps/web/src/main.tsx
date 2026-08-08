import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { routeFor } from './lib/route'
import './index.css'

/* Route dispatch is a single read of the URL. Both routes are entered by a 302
 * from FastAPI's /m/:merchantId, and everything after that is state — so there
 * is no history to manage and no router to install. */
const route = routeFor(window.location.pathname, window.location.search)

const root = document.getElementById('root')

if (root !== null) {
  createRoot(root).render(
    // Kept on in development on purpose. Strict Mode's double-invoked effects
    // are exactly the condition that would otherwise let a duplicate generation
    // request reach production, and each one costs money and a cap slot.
    <StrictMode>
      <ErrorBoundary>
        <App route={route} />
      </ErrorBoundary>
    </StrictMode>,
  )
}
