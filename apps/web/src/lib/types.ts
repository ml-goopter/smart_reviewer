import type { Locale } from './i18n'

/* Wire shapes, mirroring apps/api/app/schemas.py.
 *
 * The API serialises to camelCase via Pydantic `serialization_alias`, so these
 * names are the ones that actually arrive — not the snake_case fields on the
 * Python side.
 */

export type Suggestion = {
  id: string
  text: string
  /** Which language this suggestion was drafted in. The server returns every
   *  language the session has generated in at once and the screen shows only
   *  the matching ones — filtering server-side would make each switch a
   *  round-trip, and GET /sessions is a write that marks the session opened. */
  language: Locale
}

export type Merchant = {
  name: string
  /** Null, not absent: PublicMerchant declares `category: str | None`. */
  category: string | null
}

export type Session = {
  merchant: Merchant
  session: { expiresAt: string }
  suggestions: Suggestion[]
  /** Languages this session has no generations left in. Sent by the server
   *  because the cap is its state: a session survives a reload and the trip to
   *  Google, so a count kept here would restart at zero each load. */
  cappedLanguages: Locale[]
  /** The only destination the browser is ever allowed to navigate to. It is
   *  chosen by the server and never constructed, edited, or defaulted here. */
  googleReviewUrl: string
}

export type GeneratedBatch = {
  suggestions: Suggestion[]
  /** Whether this language's allowance is spent counting this batch. Without
   *  it the limit is only discoverable from a request that fails, so Generate
   *  More would survive one press past the last one it can honour. */
  capReached: boolean
}

/** What survives the trip to Google and back. The session token is
 *  deliberately not a member: it lives in the URL and nowhere else. */
export type Draft = {
  selectedId: string | null
  /** The suggestion as generated, so Reset has something to restore. */
  originalText: string
  reviewText: string
}

/* How a failure should read to the customer, decided from the status code and
 * nothing else. The backend also returns a machine-readable `error` string; it
 * is deliberately discarded, because every path that could put it on screen is
 * a path that leaks which of several private causes applied. */
export type FailureKind =
  /** 404 / 410 — the token is dead. Terminal: nothing on the page is usable. */
  | 'session-gone'
  /** 429 — generation cap or per-IP limit. Suggestions stay usable. */
  | 'rate-limited'
  /** 502 / 503 — the AI provider is unreachable. Retryable. */
  | 'provider-down'
  /** fetch itself rejected: offline, DNS, TLS, cancelled. Retryable. */
  | 'network'
  /** anything else, including 500. */
  | 'server'
