import { CATALOGS, LOCALES, type Locale } from './i18n'

/* Which language the customer reads, where that comes from, and how it
 * survives the next scan.
 *
 * localStorage, not the sessionStorage draft.ts chose: the case this feature
 * exists for is a Chinese reader whose phone is set to English, and without
 * persistence they would pick their language again at every merchant, forever.
 * A language preference is not private the way a half-written review is, so
 * the tab-scoping that protects a draft buys nothing here.
 *
 * No React in this module. The ladder and the tag mapping are the parts most
 * worth testing, and they are testable without rendering anything.
 */

const STORAGE_KEY = 'smart-reviewer:locale'

/** What an unrecognised browser is served. Also what the merchant's printed
 *  material is in. */
const FALLBACK: Locale = 'en'

/** Regions written with Traditional characters. Hong Kong and Macau read the
 *  same script as Taiwan; every other zh region is Simplified. */
const HANT_REGIONS = new Set(['tw', 'hk', 'mo'])

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value)
}

/** One BCP-47 tag to a locale we serve, or null if we serve none of it.
 *
 *  Null rather than a fallback, so `detectLocale` can keep walking the
 *  customer's list: somebody configured as `["fr-CA", "zh-TW"]` reads Chinese,
 *  and collapsing the first tag to English would never find that out.
 */
export function localeFromTag(tag: string): Locale | null {
  const parts = tag.toLowerCase().split('-')

  if (parts[0] === 'en') return 'en'
  if (parts[0] !== 'zh') return null

  // An explicit script subtag outranks the region: zh-Hans-HK is a Simplified
  // reader who happens to be in Hong Kong, not a Traditional one.
  if (parts.includes('hant')) return 'zh-Hant'
  if (parts.includes('hans')) return 'zh-Hans'

  if (parts.some((part) => HANT_REGIONS.has(part))) return 'zh-Hant'

  // Bare `zh`, and every region that is not Traditional. CLDR resolves an
  // unqualified `zh` to Simplified.
  return 'zh-Hans'
}

/** First supported entry in the customer's ordered language list. */
export function detectLocale(tags: readonly string[]): Locale {
  for (const tag of tags) {
    const locale = localeFromTag(tag)
    if (locale !== null) return locale
  }

  return FALLBACK
}

export function storedLocale(): Locale | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)

    // Validated, never trusted. This value reaches document.documentElement.lang
    // and indexes CATALOGS, and any script that reaches this origin can write it.
    return isLocale(stored) ? stored : null
  } catch {
    // Absent as well as throwing: `localStorage` is undefined in some embedded
    // environments, and a sandboxed iframe throws on read, not just on write.
    return null
  }
}

export function storeLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Private browsing and disabled storage both throw. The choice still
    // applies to the page in front of the customer; it just will not survive
    // the next scan, which is a better outcome than a crash on a tap.
  }
}

/** An explicit choice, else the phone's settings, else English. */
export function initialLocale(): Locale {
  const stored = storedLocale()
  if (stored !== null) return stored

  // The DOM types declare `languages` as always present, but it is absent in
  // some in-app WebViews — the same environments that already force this app
  // to optional-chain `navigator.clipboard`.
  const configured = navigator.languages as readonly string[] | undefined

  return detectLocale(configured ?? [navigator.language])
}

export function applyLocale(locale: Locale): void {
  // Not decorative for these two. A browser picks Traditional or Simplified
  // glyph forms for the same codepoint from this attribute, so without it one
  // of the two Chinese locales renders in the other's shapes.
  document.documentElement.lang = locale

  // Kept as generic in every locale as index.html's is: the tab title and
  // browser history must not record which business was visited.
  document.title = CATALOGS[locale].document.title
}
