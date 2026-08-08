import type { Draft } from './types'

/* The edited review has to survive the trip to Google and back.
 *
 * React state does not: the customer leaves via window.location, and the entry
 * redirect sends Cache-Control: no-store, which disables bfcache — so pressing
 * back re-executes the bundle from scratch. Without this the customer returns
 * to a session that is still valid and finds their edits gone.
 *
 * sessionStorage, not localStorage: tab-scoped, so a phone handed round a table
 * does not leak one person's draft into the next person's tab.
 */

const PREFIX = 'smart-reviewer:draft:'

/* FNV-1a, 32-bit. The draft is namespaced per session, but writing the token
 * itself into storage — even as a key name — would put a live capability
 * somewhere other than the URL, which is the one rule §42 states outright.
 * A digest cannot be replayed; sessionStorage is readable by any script that
 * reaches this origin.
 *
 * Not cryptographic and does not need to be: it namespaces a handful of
 * same-tab sessions, and the worst a collision does is restore one draft into
 * another session's editor — both belonging to the same person, in the same
 * tab, within the same 24 hours.
 */
function keyFor(token: string): string {
  let hash = 0x811c9dc5

  for (let i = 0; i < token.length; i++) {
    hash ^= token.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }

  return PREFIX + (hash >>> 0).toString(16)
}

export function saveDraft(token: string, draft: Draft): void {
  try {
    sessionStorage.setItem(keyFor(token), JSON.stringify(draft))
  } catch {
    // Private browsing and storage-quota failures both throw here. Losing the
    // draft is a degraded experience; throwing would take the editor down with
    // it on every keystroke.
  }
}

export function loadDraft(token: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(keyFor(token))
    if (raw === null) return null

    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object') return null

    const { selectedId, originalText, reviewText } = parsed as Record<string, unknown>

    // Storage is attacker-writable in the same sense any client state is, and
    // this feeds a textarea and a suggestionId that goes back to the server.
    // Anything not exactly the expected shape is discarded rather than coerced.
    if (typeof originalText !== 'string' || typeof reviewText !== 'string') return null
    if (selectedId !== null && typeof selectedId !== 'string') return null

    return { selectedId, originalText, reviewText }
  } catch {
    return null
  }
}

export function clearDraft(token: string): void {
  try {
    sessionStorage.removeItem(keyFor(token))
  } catch {
    // See saveDraft.
  }
}
