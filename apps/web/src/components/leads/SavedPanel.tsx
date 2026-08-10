import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchSaved } from '../../lib/leadsApi'
import type { SavedMerchant } from '../../lib/leadTypes'
import { CopyButton } from './CopyButton'

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
  })
}

/** Matches the API's own default `limit`. It is also the yardstick for whether
 *  another page exists, so the two must not drift apart. */
const PAGE_SIZE = 50

/** Appended by id. The API pages with OFFSET over a newest-first list, so a
 *  merchant saved by anyone between two requests shifts the window and repeats
 *  a row — and two rows sharing a React key is unsupported behaviour, not a
 *  cosmetic duplicate. */
function append(
  current: SavedMerchant[],
  page: readonly SavedMerchant[],
): SavedMerchant[] {
  const seen = new Set(current.map((merchant) => merchant.id))
  return [...current, ...page.filter((merchant) => !seen.has(merchant.id))]
}

/** Everything the crawler has saved. Costs no Google call, which is the point:
 *  without it, a URL not pasted in the moment is recoverable only by paying to
 *  find the same listing again. */
export function SavedPanel({ onEdit }: { onEdit: (merchantId: string) => void }) {
  const [merchants, setMerchants] = useState<SavedMerchant[] | null>(null)
  const [error, setError] = useState(false)
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false)

  /* One request at a time, guarded by a ref set synchronously before the first
   * await — `loading` is a render behind, and both Strict Mode's double-invoked
   * effect and an impatient double-tap fire well inside that window. A second
   * request either appends the same page twice or lands a stale first page on
   * top of a second one. Same guard as the reviewer's generation. */
  const inFlight = useRef(false)

  const load = useCallback((offset: number) => {
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    fetchSaved(PAGE_SIZE, offset)
      .then((body) => {
        // A body without the array is a failure, not an empty list. Rendering
        // "Nothing saved yet" for it would state something false, and reading
        // `.length` off it takes the whole panel down through the error
        // boundary.
        if (!Array.isArray(body?.merchants)) {
          setError(true)
          return
        }
        // Appended, not replaced: the rows already on screen are the
        // operator's list, and a later page does not supersede them.
        setMerchants((current) =>
          offset === 0 ? [...body.merchants] : append(current ?? [], body.merchants),
        )
        // A short page is the end of the list. A full one only might be, and
        // offering one more click is cheaper than hiding rows that exist.
        setMore(body.merchants.length === PAGE_SIZE)
        // A page that arrives clears the failure of the one before it.
        setError(false)
      })
      .catch(() => setError(true))
      .finally(() => {
        inFlight.current = false
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    load(0)
  }, [load])

  // Only while there is nothing to lose. Past the first page the failure is
  // reported under the table instead: replacing rows the operator already has
  // with an error would cost them the list to report a page they can retry.
  if (error && merchants === null) {
    return (
      <p className="lead-error" role="alert">
        Could not load saved merchants.
      </p>
    )
  }
  if (merchants === null) return <p className="lead-empty">Loading…</p>
  if (merchants.length === 0) {
    return (
      <p className="lead-empty" role="status">
        Nothing saved yet. Run a search to add one.
      </p>
    )
  }

  return (
    <>
      <table className="lead-table">
        <thead>
          <tr>
            <th>Merchant</th>
            <th>Status</th>
            <th>Saved</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {merchants.map((merchant) => (
            <tr key={merchant.id}>
              <td>
                <span className="lead-name">{merchant.name}</span>
                <span className="lead-sub">
                  {merchant.city ?? '—'} · {merchant.slug}
                </span>
              </td>
              <td>{merchant.status}</td>
              <td>{day(merchant.createdAt)}</td>
              <td className="lead-actions">
                {merchant.url === null ? (
                  <span className="lead-sub">no URL</span>
                ) : (
                  <CopyButton url={merchant.url} label="Copy URL" />
                )}
                <button
                  type="button"
                  className="lead-btn lead-btn--quiet"
                  onClick={() => onEdit(merchant.id)}
                >
                  Edit
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* The rows already fetched stay on screen. `more` is still true, so the
          button below is the retry. */}
      {error && (
        <p className="lead-error" role="alert">
          Could not load more saved merchants.
        </p>
      )}

      {/* Older rows are otherwise unreachable, and nothing on screen would say
          they exist — in the one view that recovers a URL without paying
          Google for the listing again. */}
      {more && (
        <button
          type="button"
          className="lead-btn lead-btn--quiet"
          disabled={loading}
          onClick={() => load(merchants.length)}
        >
          {loading ? 'Loading…' : 'Load more'}
        </button>
      )}
    </>
  )
}
