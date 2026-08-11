import { useEffect, useState } from 'react'

import { useMessages } from '../../lib/i18n/context'
import type { Messages } from '../../lib/i18n'
import { LeadFailure, fetchCategories, saveMerchant, search } from '../../lib/leadsApi'
import {
  loadCriteria,
  loadResults,
  saveCriteria,
  saveResults,
} from '../../lib/leadSearchStore'
import type {
  LeadCategory,
  LeadResult,
  LeadSearchResponse,
  SearchCriteria,
} from '../../lib/leadTypes'
import { CopyButton } from './CopyButton'

/** The API's `error` code to copy the operator can act on.
 *
 *  Indexed with a widened type because the code arrives from the server: one
 *  this build has no entry for falls back to the status rather than to
 *  `undefined` rendering as a blank error. */
function message(failures: Messages['leads']['failures'], error: unknown): string {
  if (error instanceof LeadFailure) {
    const known = (failures as Record<string, unknown>)[error.code]
    // Typed rather than assumed: `status` in the same namespace is a function,
    // and a server code colliding with it would otherwise render as source.
    return typeof known === 'string' ? known : failures.status(error.status)
  }
  return failures.unknown
}

function distance(metres: number | null): string {
  if (metres === null) return '—'
  return metres < 1000 ? `${metres} m` : `${(metres / 1000).toFixed(1)} km`
}

const DEFAULT_RADIUS_METERS = 5000

/** Blank fields are omitted rather than sent as empty strings: the API forbids
 *  unknown and out-of-range values, and "" is not the same as "nothing typed". */
function criteriaFrom(form: HTMLFormElement): SearchCriteria {
  const data = new FormData(form)
  const text = (key: string) => {
    const value = String(data.get(key) ?? '').trim()
    return value === '' ? undefined : value
  }
  const number = (key: string) => {
    const value = text(key)
    return value === undefined ? undefined : Number(value)
  }

  // An emptied radius falls back to the default rather than to `Number('')`,
  // which is 0 — below the API's `ge=1`, so the search comes back as "some
  // criteria are out of range", and the 0 is persisted and restored.
  const criteria: SearchCriteria = {
    location: String(data.get('location') ?? '').trim(),
    radiusMeters: number('radiusMeters') ?? DEFAULT_RADIUS_METERS,
  }

  // Assigned only when present, rather than set to undefined: the API forbids
  // unknown keys and rejects out-of-range values, and an absent criterion is
  // not the same statement as an empty one.
  const textQuery = text('textQuery')
  if (textQuery !== undefined) criteria.textQuery = textQuery
  const category = text('category')
  if (category !== undefined) criteria.category = category
  const minRating = number('minRating')
  if (minRating !== undefined) criteria.minRating = minRating
  const maxRating = number('maxRating')
  if (maxRating !== undefined) criteria.maxRating = maxRating
  const maxReviewCount = number('maxReviewCount')
  if (maxReviewCount !== undefined) criteria.maxReviewCount = maxReviewCount

  return criteria
}

/** searchText rejects an empty textQuery, so a location on its own cannot be
 *  answered. Checked here as well as on the server: the server check is what
 *  makes it true for an open endpoint, this one is what stops a billed geocode
 *  and a round trip before the operator has said what to look for. */
function hasSubject(criteria: SearchCriteria): boolean {
  return criteria.textQuery !== undefined || criteria.category !== undefined
}

const DEFAULT_CRITERIA: SearchCriteria = {
  location: 'Burnaby',
  radiusMeters: DEFAULT_RADIUS_METERS,
}

export function SearchPanel({ onEdit }: { onEdit: (merchantId: string) => void }) {
  const leads = useMessages().leads
  const t = leads.search

  const [categories, setCategories] = useState<LeadCategory[]>([])
  // Restored once, on mount. The panel unmounts whenever the operator switches
  // to Saved or opens an editor, and re-running the search to get back here
  // costs real money.
  const [restored] = useState(() => loadCriteria())
  const [response, setResponse] = useState<LeadSearchResponse | null>(() => loadResults())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Every save in flight, not the last one: with a single id, finishing row A
  // clears row B's "Saving…" and re-enables its button mid-POST, which invites
  // a duplicate save.
  const [saving, setSaving] = useState<readonly string[]>([])
  // What the save response said beyond the row itself — an existing row was
  // returned unchanged, or its status means the URL will not open.
  const [notice, setNotice] = useState<string | null>(null)

  const initial = restored ?? DEFAULT_CRITERIA
  const [category, setCategory] = useState(initial.category ?? '')

  // One place results are persisted, covering the search itself and the row
  // patched after a save — so the Saved badge survives the trip too. Writing
  // inside the state updater instead would run twice under StrictMode.
  useEffect(() => {
    saveResults(response)
  }, [response])

  useEffect(() => {
    // The dropdown is served rather than hard-coded here: a category this
    // bundle offers but the server rejects is a 400 nobody can act on.
    fetchCategories()
      // A body without the array leaves the dropdown empty rather than taking
      // the panel down through the error boundary — the same outcome the
      // catch below already produces for a failed request.
      .then((body) => setCategories(Array.isArray(body?.categories) ? body.categories : []))
      .catch(() => setCategories([]))
  }, [])

  async function run(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const criteria = criteriaFrom(event.currentTarget)

    setNotice(null)

    if (!hasSubject(criteria)) {
      // Nothing is sent: the same refusal the server would give, without the
      // round trip or the billed geocode behind it.
      setError(leads.failures.criteria_too_broad)
      setResponse(null)
      return
    }

    setBusy(true)
    setError(null)
    try {
      setResponse(await search(criteria))
    } catch (failure) {
      setResponse(null)
      setError(message(leads.failures, failure))
    } finally {
      setBusy(false)
    }
  }

  async function save(result: LeadResult) {
    setSaving((current) => [...current, result.placeId])
    setError(null)
    setNotice(null)
    try {
      const saved = await saveMerchant(result.placeId)
      // `created` and `note` are the whole difference between a fresh save and
      // one that found an existing row — including an archived one, whose URL
      // will not open. Neither is visible in the patched row.
      setNotice(
        saved.note !== null
          ? `${saved.merchant.name}: ${saved.note}`
          : saved.created
            ? null
            : t.alreadySaved(saved.merchant.name),
      )
      // Patch just this row rather than re-running the search: a second search
      // is a second bill, and the operator's list would reorder underneath them.
      setResponse((current) =>
        current === null
          ? current
          : {
            ...current,
            results: current.results.map((row) =>
              row.placeId === result.placeId
                ? {
                  ...row,
                  saved: true,
                  merchantId: saved.merchant.id,
                  status: saved.merchant.status,
                  url: saved.merchant.url,
                }
                : row,
            ),
          },
      )
    } catch (failure) {
      setError(message(leads.failures, failure))
    } finally {
      setSaving((current) => current.filter((placeId) => placeId !== result.placeId))
    }
  }

  return (
    <div className="lead-panel">
      {/* Uncontrolled inputs seeded from what was restored: seven controlled
          fields would re-render the whole panel per keystroke to solve a
          problem `defaultValue` already solves on mount. onChange persists the
          criteria so unsubmitted edits survive the trip too. */}
      <form
        className="lead-form"
        onSubmit={run}
        onChange={(event) => saveCriteria(criteriaFrom(event.currentTarget))}
      >
        <label className="lead-field">
          <span>{t.location}</span>
          <input
            name="location"
            defaultValue={initial.location}
            required
            placeholder={t.locationPlaceholder}
          />
        </label>
        <label className="lead-field">
          <span>{t.radius}</span>
          <input
            name="radiusMeters"
            type="number"
            defaultValue={initial.radiusMeters}
            min={1}
            max={50000}
          />
        </label>
        <label className="lead-field">
          <span>{t.category}</span>
          {/* Controlled, unlike its neighbours: the options arrive from the
              server after mount, and a `defaultValue` naming an option that
              does not exist yet is discarded — so a restored category silently
              reverted to Any. */}
          <select
            name="category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="">{t.anyCategory}</option>
            {categories.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {/* Translated by the value, and the server's own label when
                    this build has no entry for it — an option that renders
                    blank would be worse than one in English. */}
                {(leads.categories as Record<string, string | undefined>)[entry.value] ??
                  entry.label}
              </option>
            ))}
          </select>
        </label>
        {/* All free text goes in one box, because it goes to Google as one
            `textQuery`. The API offers no field that matches a merchant name
            any differently, so splitting this would promise a distinction
            that does not exist. */}
        <label className="lead-field">
          <span>{t.textQuery}</span>
          {/* Mirrors the API's own bound: without it an over-long paste comes
              back as "Some criteria are out of range", which names no
              criterion for the operator to act on. */}
          <input
            name="textQuery"
            defaultValue={initial.textQuery ?? ''}
            maxLength={200}
            placeholder={t.textQueryPlaceholder}
          />
        </label>
        <label className="lead-field">
          <span>{t.ratingMin}</span>
          <input
            name="minRating"
            type="number"
            step="0.1"
            min={0}
            max={5}
            defaultValue={initial.minRating ?? ''}
          />
        </label>
        <label className="lead-field">
          <span>{t.ratingMax}</span>
          <input
            name="maxRating"
            type="number"
            step="0.1"
            min={0}
            max={5}
            defaultValue={initial.maxRating ?? ''}
          />
        </label>
        <label className="lead-field">
          <span>{t.maxReviews}</span>
          <input
            name="maxReviewCount"
            type="number"
            min={0}
            placeholder="200"
            defaultValue={initial.maxReviewCount ?? ''}
          />
        </label>

        <button type="submit" className="lead-btn" disabled={busy}>
          {busy ? t.submitting : t.submit}
        </button>
      </form>

      {/* Stated up front rather than only after a refusal: the requirement is
          not guessable from a form whose only required field is the location. */}
      <p className="lead-note">{t.note}</p>

      {/* The live region is the container, not the message: a region that
          arrives in the same commit as its first text is usually not announced
          at all, so a failed search would be silent. */}
      <div role="status" aria-live="polite">
        {error !== null && <p className="lead-error">{error}</p>}
        {notice !== null && <p className="lead-warning">{notice}</p>}
      </div>

      {/* The funnel and the empty-list explanation are what a search says; the
          table is not, and announcing sixty rows would bury them. */}
      <div role="status" aria-live="polite">
        {response !== null && (
          <>
            <p className="lead-resolved">
              {t.resolved(response.resolvedLocation.formatted)}
            </p>
            <p className="lead-funnel">{t.funnel(response.searched, response.matched)}</p>
            {response.partial && (
              <p className="lead-warning">{t.partial}</p>
            )}
            {response.truncated && (
              <p className="lead-warning">{t.truncated}</p>
            )}
            {response.results.length === 0 && (
              <p className="lead-empty">{t.empty}</p>
            )}
          </>
        )}
      </div>

      {response !== null && response.results.length > 0 && (
        <table className="lead-table">
          <thead>
            <tr>
              <th>{t.merchant}</th>
              <th>{t.rating}</th>
              <th>{t.reviews}</th>
              <th>{t.distance}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {response.results.map((result) => (
              <tr key={result.placeId}>
                <td>
                  <span className="lead-name">{result.name}</span>
                  <span className="lead-sub">
                    {result.category ?? t.uncategorised}
                    {result.address === null ? '' : ` · ${result.address}`}
                  </span>
                  {/* The two things a prospector acts on. Google returns
                      them per result and the tool exists to reach the
                      merchant, so hiding them costs a second lookup. */}
                  {(result.phone !== null || result.website !== null) && (
                    <span className="lead-sub">
                      {result.phone}
                      {result.phone !== null && result.website !== null && ' · '}
                      {result.website !== null && (
                        <a href={result.website} target="_blank" rel="noreferrer">
                          {t.website}
                        </a>
                      )}
                    </span>
                  )}
                </td>
                <td>{result.rating === null ? '—' : `${result.rating} ★`}</td>
                {/* "0" would assert a fact Google marked unknown, and the
                    review-count cap is the filter this tool turns on. */}
                <td>{result.reviewCount ?? '—'}</td>
                <td>{distance(result.distanceMeters)}</td>
                <td className="lead-actions">
                  {result.saved ? (
                    <>
                      <span className="lead-badge">{t.savedBadge}</span>
                      {result.url === null ? (
                        <span className="lead-sub">
                          {result.status} · {leads.noUrl}
                        </span>
                      ) : (
                        <CopyButton url={result.url} label={leads.copyUrl} />
                      )}
                      {result.merchantId !== null && (
                        <button
                          type="button"
                          className="lead-btn lead-btn--quiet"
                          onClick={() => onEdit(result.merchantId!)}
                        >
                          {leads.edit}
                        </button>
                      )}
                    </>
                  ) : (
                    <button
                      type="button"
                      className="lead-btn"
                      disabled={saving.includes(result.placeId)}
                      onClick={() => save(result)}
                    >
                      {saving.includes(result.placeId) ? t.saving : t.save}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
