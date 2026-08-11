import { useRef, useState } from 'react'

import '../../leads.css'
import { useMessages } from '../../lib/i18n/context'
import { TopBar } from '../TopBar'
import { SavedPanel } from './SavedPanel'
import { SearchPanel } from './SearchPanel'

/** The internal tool's shell.
 *
 *  Search and Saved are tabs rather than routes: they are two views of the same
 *  task and nothing outside this screen ever links to one of them. The context
 *  editor *is* a route, because a merchant is a thing worth sending someone.
 */
const TAB_IDS = ['search', 'saved'] as const

type TabId = (typeof TAB_IDS)[number]

export function LeadCrawler({ onEdit }: { onEdit: (merchantId: string) => void }) {
  const messages = useMessages()
  const [tab, setTab] = useState<TabId>('search')
  const tabs = useRef<Record<string, HTMLButtonElement | null>>({})

  /** Arrow keys move between tabs, which is what the role promises. Combined
   *  with the roving tabindex below, Tab then leaves the tablist for the panel
   *  instead of stepping through every tab in it. */
  function onKeyDown(event: React.KeyboardEvent) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    event.preventDefault()
    const index = TAB_IDS.indexOf(tab)
    const next = TAB_IDS[(index + step + TAB_IDS.length) % TAB_IDS.length]!
    setTab(next)
    tabs.current[next]?.focus()
  }

  return (
    <div className="leads">
      {/* The same bar and drawer the customer screens carry. The language it
        * sets is one choice for the whole app — an operator who reads Chinese
        * reads it here too, and a second switcher would be a second place to
        * set the same thing. */}
      <TopBar />

      <header className="lead-header">
        <h1>{messages.leads.title}</h1>
        {/* Real tab semantics, not buttons that look like tabs: the Search tab
            and the search form's submit button would otherwise be two controls
            with the same accessible name on one screen. The role is only worth
            announcing if the whole pattern is there — the panel it controls,
            and the arrow keys that reach it. */}
        <nav className="lead-tabs" role="tablist" aria-label={messages.leads.viewsLabel}>
          {TAB_IDS.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`lead-tab-${id}`}
              aria-controls="lead-tabpanel"
              aria-selected={tab === id}
              tabIndex={tab === id ? 0 : -1}
              ref={(node) => {
                tabs.current[id] = node
              }}
              className={tab === id ? 'lead-tab lead-tab--on' : 'lead-tab'}
              onClick={() => setTab(id)}
              onKeyDown={onKeyDown}
            >
              {messages.leads.tabs[id]}
            </button>
          ))}
        </nav>
      </header>

      {/* One panel element, relabelled: both tabs show the same kind of thing
          in the same place, and two panels would mean two ids for one slot. */}
      <div id="lead-tabpanel" role="tabpanel" aria-labelledby={`lead-tab-${tab}`}>
        {tab === 'search' ? (
          <SearchPanel onEdit={onEdit} />
        ) : (
          <SavedPanel onEdit={onEdit} />
        )}
      </div>
    </div>
  )
}
