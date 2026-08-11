import type { Locale } from './i18n'
import { isLocale } from './locale'
import type { FailureKind, GeneratedBatch, Session, Suggestion } from './types'

/* The four calls the SPA makes. `POST /api/review/sessions` is absent on
 * purpose — FastAPI calls it when serving /m/:merchantId, and a session the
 * browser could mint would defeat the per-IP rate limit that protects it.
 *
 * Same origin throughout, so no base URL and no CORS. In development Vite
 * proxies /api to FastAPI; in production nginx does.
 */

export class ApiFailure extends Error {
  readonly kind: FailureKind

  constructor(kind: FailureKind) {
    // The message is for a developer reading a stack trace. Customer-facing
    // copy is chosen from `kind` at the call site — never from here, and never
    // from the backend's response body.
    super(`request failed: ${kind}`)
    this.name = 'ApiFailure'
    this.kind = kind
  }
}

function classify(status: number): FailureKind {
  if (status === 404 || status === 410) return 'session-gone'
  if (status === 429) return 'rate-limited'
  if (status === 502 || status === 503) return 'provider-down'
  return 'server'
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response

  try {
    response = await fetch(path, init)
  } catch {
    // Distinguished from a server error because it is the one failure a
    // customer can actually fix, by moving somewhere with signal.
    throw new ApiFailure('network')
  }

  if (!response.ok) throw new ApiFailure(classify(response.status))

  return response
}

const json = { 'Content-Type': 'application/json' }

/** The only value in the app that is handed to a navigation.
 *
 *  It comes from the server, but not from anywhere the server computes: the
 *  seed script copies `google_review_url` out of a merchant's YAML verbatim,
 *  because some listings use a short g.page link. A `javascript:` URL there
 *  would execute on this origin, in a tab whose address bar holds a live
 *  session token. One check is cheaper than trusting the whole onboarding path.
 */
function isSafeDestination(url: unknown): url is string {
  if (typeof url !== 'string' || url === '') return false

  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

export async function loadSession(token: string): Promise<Session> {
  const response = await request(`/api/review/sessions/${encodeURIComponent(token)}`)
  const data = (await response.json()) as Session

  // Checked here rather than at the tap. Everything else on the page is
  // cosmetic if it is wrong, but a bad destination means the customer goes
  // nowhere — and would find out at the very last step, after doing the work.
  if (!isSafeDestination(data.googleReviewUrl)) throw new ApiFailure('session-gone')

  // Normalised rather than trusted: an API build without the field would put
  // `undefined` where the reviewer calls `.includes`, and an unknown tag would
  // sit in the list forever, silently hiding Generate More for nothing.
  return {
    ...data,
    cappedLanguages: Array.isArray(data.cappedLanguages)
      ? data.cappedLanguages.filter(isLocale)
      : [],
  }
}

export async function generateSuggestions(
  token: string,
  language: Locale,
): Promise<GeneratedBatch> {
  const response = await request(
    `/api/review/sessions/${encodeURIComponent(token)}/suggestions`,
    { method: 'POST', headers: json, body: JSON.stringify({ language }) },
  )

  const data = (await response.json()) as GeneratedBatch

  // A 2xx with the wrong shape would otherwise put `undefined` into the
  // suggestion list and blank the page on the next render — an unrecoverable
  // white screen where a retryable notice belongs.
  if (!Array.isArray(data?.suggestions)) throw new ApiFailure('server')

  return {
    suggestions: data.suggestions.filter(
      (item): item is Suggestion =>
        typeof item?.id === 'string' && typeof item?.text === 'string',
    ),
    // Only an explicit `true` retires the button. Anything else — an older API
    // build, a truncated body — leaves it in place, where the worst case is
    // the 429 this field exists to pre-empt rather than a customer denied the
    // generations they still have.
    capReached: data?.capReached === true,
  }
}

export async function selectSuggestion(token: string, suggestionId: string): Promise<void> {
  await request(`/api/review/sessions/${encodeURIComponent(token)}/select`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ suggestionId }),
  })
}

/** Fire-and-forget: never awaited, never allowed to reject.
 *
 *  This is analytics riding along with a navigation that is already happening.
 *  `keepalive` is what lets it survive the unload; an unhandled rejection from
 *  the same call would surface as a console error on a page that is leaving
 *  anyway, so it is swallowed here rather than at every call site.
 */
export function completeSession(
  token: string,
  body: { suggestionId?: string; reviewCopied: boolean },
): void {
  fetch(`/api/review/sessions/${encodeURIComponent(token)}/complete`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify(body),
    keepalive: true,
  }).catch(() => {})
}
