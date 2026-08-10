import type { LeadSearchResponse, SearchCriteria } from './leadTypes'

/* The last search survives leaving the screen.
 *
 * A search costs two to four billed Google requests, and the operator leaves
 * the results constantly: switching to Saved, opening a merchant's editor,
 * coming back. Every one of those unmounts the panel — the editor unmounts the
 * whole crawler — so without this the list is gone and the only way back to it
 * is to pay for it again.
 *
 * sessionStorage rather than lifting state: tab state is what this is, and the
 * editor is a separate route, so no common ancestor stays mounted across the
 * trip. Same mechanism and same reasoning as the reviewer's draft.
 *
 * Nothing here is a capability: Place IDs and ratings are public, and the
 * criteria are what the operator just typed. That is why this stores values
 * directly, where draft.ts has to hash its key.
 */

// Two keys, not one: criteria are rewritten on every keystroke and results are
// up to sixty rows. Sharing a key would re-serialise the whole result set on
// each character typed.
const CRITERIA_KEY = 'lead-crawler:criteria'
const RESULTS_KEY = 'lead-crawler:results'

function write(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Private browsing and quota failures throw here. Losing the restored list
    // is a degraded experience; throwing would take the panel down with it on
    // every keystroke.
  }
}

function read(key: string): unknown {
  try {
    const raw = sessionStorage.getItem(key)
    return raw === null ? null : JSON.parse(raw)
  } catch {
    return null
  }
}

export function saveCriteria(criteria: SearchCriteria): void {
  write(CRITERIA_KEY, criteria)
}

export function saveResults(response: LeadSearchResponse | null): void {
  write(RESULTS_KEY, response)
}

/* Storage is writable by anything on this origin, and these values are
 * rendered and posted back. Anything not the expected shape is discarded
 * rather than coerced — a malformed entry means no restore, not a broken
 * screen. */

export function loadCriteria(): SearchCriteria | null {
  const parsed = read(CRITERIA_KEY)
  if (parsed === null || typeof parsed !== 'object') return null

  const { location, radiusMeters } = parsed as Record<string, unknown>
  if (typeof location !== 'string' || typeof radiusMeters !== 'number') return null

  return parsed as SearchCriteria
}

export function loadResults(): LeadSearchResponse | null {
  const parsed = read(RESULTS_KEY)
  if (parsed === null || typeof parsed !== 'object') return null

  const { results, searched, matched, resolvedLocation } = parsed as Record<
    string,
    unknown
  >
  if (!Array.isArray(results)) return null
  if (typeof searched !== 'number' || typeof matched !== 'number') return null
  if (resolvedLocation === null || typeof resolvedLocation !== 'object') return null

  return parsed as LeadSearchResponse
}
