/* The crawler's five calls.
 *
 * Unlike the reviewer's client, this one reads the error *code* out of the
 * response body. The reviewer deliberately does not — its copy is chosen from
 * the status alone so a backend message can never reach a customer's screen.
 * Here the reader is the operator who typed the criteria, and "that postal code
 * does not exist" is something only the body can tell them.
 */

import type {
  LeadCategory,
  LeadSearchResponse,
  MerchantContext,
  ReviewContext,
  SaveMerchantResponse,
  SavedMerchant,
  SearchCriteria,
} from './leadTypes'

export class LeadFailure extends Error {
  readonly status: number
  /** The API's stable machine code, e.g. `location_not_found`. Empty when the
   *  response carried no body — a network failure, or a proxy's own error. */
  readonly code: string

  constructor(status: number, code: string) {
    super(`lead request failed: ${status} ${code}`)
    this.name = 'LeadFailure'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response

  try {
    response = await fetch(path, init)
  } catch {
    throw new LeadFailure(0, 'network')
  }

  if (!response.ok) {
    let code = ''
    try {
      const body = (await response.json()) as { error?: unknown }
      if (typeof body.error === 'string') code = body.error
    } catch {
      // A body that is not JSON tells us nothing the status has not already.
    }
    throw new LeadFailure(response.status, code)
  }

  return (await response.json()) as T
}

const json = { 'Content-Type': 'application/json' }

export function fetchCategories(): Promise<{ categories: LeadCategory[] }> {
  return request('/api/leads/categories')
}

export function search(criteria: SearchCriteria): Promise<LeadSearchResponse> {
  return request('/api/leads/search', {
    method: 'POST',
    headers: json,
    body: JSON.stringify(criteria),
  })
}

/** Sends the Place ID and nothing else: the server re-fetches the listing, so
 *  no field on this screen can become a fact in the database. */
export function saveMerchant(placeId: string): Promise<SaveMerchantResponse> {
  return request('/api/leads/merchants', {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ placeId }),
  })
}

/** Paginated, because the list is the only way back to a URL that was not
 *  pasted in the moment — and past the first page it would otherwise be gone. */
export function fetchSaved(
  limit = 50,
  offset = 0,
): Promise<{ merchants: SavedMerchant[] }> {
  return request(`/api/leads/merchants?limit=${limit}&offset=${offset}`)
}

export function fetchContext(merchantId: string): Promise<MerchantContext> {
  return request(`/api/leads/merchants/${encodeURIComponent(merchantId)}/context`)
}

export function putContext(
  merchantId: string,
  context: ReviewContext,
): Promise<ReviewContext> {
  return request(`/api/leads/merchants/${encodeURIComponent(merchantId)}/context`, {
    method: 'PUT',
    headers: json,
    body: JSON.stringify(context),
  })
}

/** Resolves false when the clipboard is unavailable — an insecure origin, or a
 *  WebView that does not implement it. The caller shows the URL either way, so
 *  a failure costs a manual selection rather than the link. */
export async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
