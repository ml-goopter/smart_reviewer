import { useRef, useState } from 'react'

import '../../leads.css'
import { SavedPanel } from './SavedPanel'
import { SearchPanel } from './SearchPanel'

/** The internal tool's shell.
 *
 *  Search and Saved are tabs rather than routes: they are two views of the same
 *  task and nothing outside this screen ever links to one of them. The context
 *  editor *is* a route, because a merchant is a thing worth sending someone.
 */
const TABS = [
  { id: 'search', label: 'Search' },
  { id: 'saved', label: 'Saved' },
] as const

type TabId = (typeof TABS)[number]['id']

export function LeadCrawler({ onEdit }: { onEdit: (merchantId: string) => void }) {
  const [tab, setTab] = useState<TabId>('search')
  const tabs = useRef<Record<string, HTMLButtonElement | null>>({})

  /** Arrow keys move between tabs, which is what the role promises. Combined
   *  with the roving tabindex below, Tab then leaves the tablist for the panel
   *  instead of stepping through every tab in it. */
  function onKeyDown(event: React.KeyboardEvent) {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    event.preventDefault()
    const index = TABS.findIndex((entry) => entry.id === tab)
    const next = TABS[(index + step + TABS.length) % TABS.length]!
    setTab(next.id)
    tabs.current[next.id]?.focus()
  }

  return (
    <div className="leads">
      <header className="lead-header">
        <h1>Lead crawler</h1>
        {/* Real tab semantics, not buttons that look like tabs: the Search tab
            and the search form's submit button would otherwise be two controls
            with the same accessible name on one screen. The role is only worth
            announcing if the whole pattern is there — the panel it controls,
            and the arrow keys that reach it. */}
        <nav className="lead-tabs" role="tablist" aria-label="Lead crawler views">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              id={`lead-tab-${entry.id}`}
              aria-controls="lead-tabpanel"
              aria-selected={tab === entry.id}
              tabIndex={tab === entry.id ? 0 : -1}
              ref={(node) => {
                tabs.current[entry.id] = node
              }}
              className={tab === entry.id ? 'lead-tab lead-tab--on' : 'lead-tab'}
              onClick={() => setTab(entry.id)}
              onKeyDown={onKeyDown}
            >
              {entry.label}
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
