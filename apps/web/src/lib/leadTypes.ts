/* Wire shapes for the lead crawler, mirroring apps/api/app/schemas.py.
 *
 * Separate from types.ts because these belong to the internal tool, not to the
 * customer-facing reviewer: nothing here is ever rendered to a customer, and
 * keeping the two apart makes that visible at the import.
 */

export type ResolvedLocation = {
  query: string
  formatted: string
  lat: number
  lng: number
}

export type LeadResult = {
  placeId: string
  name: string
  category: string | null
  address: string | null
  distanceMeters: number | null
  rating: number | null
  reviewCount: number | null
  phone: string | null
  website: string | null
  saved: boolean
  merchantId: string | null
  /** Always present for a saved row: it is derived from the merchant id and
   *  exists whether or not it currently opens. */
  url: string | null
  subscription: Subscription | null
}

export type LeadSearchResponse = {
  resolvedLocation: ResolvedLocation
  /** The funnel. `searched` is what Google was asked about, `matched` is what
   *  survived the filters it cannot apply. */
  searched: number
  matched: number
  partial: boolean
  /** Google still had pages when the result ceiling was reached. Without it a
   *  deliberately shortened list reads as everything Google had. */
  truncated: boolean
  results: LeadResult[]
}

export type SavedMerchant = {
  id: string
  name: string
  slug: string
  category: string | null
  address: string | null
  city: string | null
  website: string | null
  googlePlaceId: string | null
  googleRating: number | null
  googleReviewCount: number | null
  googleSyncedAt: string | null
  createdAt: string
  url: string | null
  /** Null when the merchant has never been subscribed — not an object of
   *  nulls. Until it exists the merchant's URL does not open. */
  subscription: Subscription | null
}

export type SubscriptionStatus = 'ACTIVE' | 'CANCELLED' | 'PAUSED'

export type Subscription = {
  status: SubscriptionStatus
  /** The first *dead* midnight, in UTC. Do not render this: use lastValidDay,
   *  or the merchant is credited a day they do not have. */
  expiresAt: string
  /** `YYYY-MM-DD`, already resolved in the operator's timezone server-side —
   *  the browser does not know that zone, so it cannot compute this itself. */
  lastValidDay: string
  duration: number
  durationUnit: string
}

export type SaveMerchantResponse = {
  created: boolean
  merchant: SavedMerchant
}

export type ReviewContext = {
  businessSummary: string | null
  products: string[] | null
  services: string[] | null
  menuItems: string[] | null
  sellingPoints: string[] | null
  approvedKeywords: string[] | null
  experienceTopics: string[] | null
  customInstructions: string | null
}

export type MerchantContext = {
  merchant: SavedMerchant
  context: ReviewContext
}

export type LeadCategory = {
  value: string
  label: string
}

export type SearchCriteria = {
  location: string
  radiusMeters: number
  textQuery?: string
  category?: string
  minRating?: number
  maxRating?: number
  maxReviewCount?: number
}
