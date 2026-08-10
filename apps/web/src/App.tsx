import { useCallback, useEffect, useRef, useState } from 'react'

import { ContextEditor } from './components/leads/ContextEditor'
import { LeadCrawler } from './components/leads/LeadCrawler'
import { Reviewer } from './components/Reviewer'
import { UnavailableState } from './components/states'
import { routeFor, type Route } from './lib/route'

/** Resolved at boot from the URL the server redirected to.
 *
 *  The customer-facing routes never change for the lifetime of the page — they
 *  are entered by a 302 and everything after is state. The internal crawler is
 *  the exception: it moves between its list and a merchant's editor, so those
 *  two paths are pushed onto history and read back on popstate. No router
 *  library for two paths that only the operator ever sees.
 */
export function App({ route }: { route: Route }) {
  const [current, setCurrent] = useState(route)
  // Whether the entry on screen is one this app pushed. Back then pops it
  // instead of pushing a second entry — otherwise bouncing between the list
  // and three merchants leaves six entries and the browser's Back walks
  // through all of them rather than leaving the tool.
  const pushed = useRef(false)

  useEffect(() => {
    const onPop = () => {
      pushed.current = false
      setCurrent(routeFor(window.location.pathname, window.location.search))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const openEditor = useCallback((merchantId: string) => {
    const path = `/leads/${merchantId}`
    window.history.pushState(null, '', path)
    pushed.current = true
    setCurrent(routeFor(path))
  }, [])

  // history.back() only when there is an entry of ours to pop. Reached by
  // typing /leads/:id, there is none, and back() would leave the site.
  const backToList = useCallback(() => {
    if (pushed.current) {
      window.history.back()
      return
    }
    window.history.replaceState(null, '', '/leads')
    setCurrent(routeFor('/leads'))
  }, [])

  if (current.name === 'reviewer') return <Reviewer token={current.token} />

  if (current.name === 'leads') {
    return <LeadCrawler onEdit={openEditor} />
  }

  if (current.name === 'leadEditor') {
    return <ContextEditor merchantId={current.merchantId} onBack={backToList} />
  }

  return <UnavailableState reason={current.reason} />
}
