import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CATALOGS } from './i18n'
import { memoryStorage, throwingStorage } from './testing/memoryStorage'
import {
  applyLocale,
  detectLocale,
  initialLocale,
  localeFromTag,
  storeLocale,
  storedLocale,
} from './locale'

const KEY = 'smart-reviewer:locale'

/** jsdom has no localStorage, so every test supplies one. */
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.lang = 'en'
})

/** navigator.languages is an accessor on the prototype; spying there restores
 *  cleanly, where replacing the whole navigator object does not. */
function phoneLanguages(languages: string[] | undefined, language = 'en-US') {
  vi.spyOn(Navigator.prototype, 'languages', 'get').mockReturnValue(
    languages as readonly string[],
  )
  vi.spyOn(Navigator.prototype, 'language', 'get').mockReturnValue(language)
}

describe('localeFromTag', () => {
  it.each([
    ['en', 'en'],
    ['en-US', 'en'],
    ['EN-gb', 'en'],
    // Region decides when no script subtag is present.
    ['zh-TW', 'zh-Hant'],
    ['zh-HK', 'zh-Hant'],
    ['zh-MO', 'zh-Hant'],
    ['zh-CN', 'zh-Hans'],
    ['zh-SG', 'zh-Hans'],
    // CLDR resolves an unqualified zh to Simplified.
    ['zh', 'zh-Hans'],
    ['zh-Hant', 'zh-Hant'],
    ['zh-Hans', 'zh-Hans'],
    ['zh-Hant-CN', 'zh-Hant'],
  ] as const)('maps %s to %s', (tag, expected) => {
    expect(localeFromTag(tag)).toBe(expected)
  })

  it('lets an explicit script outrank the region', () => {
    // Reads Simplified, lives in Hong Kong. Region alone would send them to
    // Traditional.
    expect(localeFromTag('zh-Hans-HK')).toBe('zh-Hans')
  })

  it('returns null for a language we do not serve', () => {
    expect(localeFromTag('fr-CA')).toBeNull()
    expect(localeFromTag('vi')).toBeNull()
  })
})

describe('detectLocale', () => {
  it('takes the first entry it can serve', () => {
    expect(detectLocale(['zh-TW', 'en-US'])).toBe('zh-Hant')
  })

  it('walks past languages it cannot serve', () => {
    // Why localeFromTag returns null rather than falling back: this customer
    // reads Chinese, and stopping at fr-CA would never find that out.
    expect(detectLocale(['fr-CA', 'zh-TW', 'en'])).toBe('zh-Hant')
  })

  it('falls back to English when nothing matches', () => {
    expect(detectLocale(['fr', 'de', 'vi'])).toBe('en')
  })

  it('falls back to English on an empty list', () => {
    expect(detectLocale([])).toBe('en')
  })
})

describe('storage', () => {
  it('round-trips a locale', () => {
    storeLocale('zh-Hant')

    expect(storedLocale()).toBe('zh-Hant')
  })

  it('reports nothing when unset', () => {
    expect(storedLocale()).toBeNull()
  })

  it('rejects a value that is not a locale we serve', () => {
    // This value reaches document.documentElement.lang and indexes CATALOGS,
    // and any script on this origin can write it.
    localStorage.setItem(KEY, 'zh-Hant"><script>')

    expect(storedLocale()).toBeNull()
  })

  it('survives storage that throws on read and write', () => {
    vi.stubGlobal('localStorage', throwingStorage())

    expect(() => storeLocale('zh-Hans')).not.toThrow()
    expect(storedLocale()).toBeNull()
  })

  it('survives storage that is absent entirely', () => {
    // jsdom's own situation, and some embedded WebViews'.
    vi.stubGlobal('localStorage', undefined)

    expect(() => storeLocale('zh-Hans')).not.toThrow()
    expect(storedLocale()).toBeNull()
  })
})

describe('initialLocale', () => {
  it('prefers an explicit choice over the phone settings', () => {
    phoneLanguages(['zh-CN'], 'zh-CN')
    localStorage.setItem(KEY, 'en')

    expect(initialLocale()).toBe('en')
  })

  it('detects from the phone when nothing is stored', () => {
    phoneLanguages(['zh-TW', 'en'], 'zh-TW')

    expect(initialLocale()).toBe('zh-Hant')
  })

  it('detects when storage is unreadable', () => {
    vi.stubGlobal('localStorage', throwingStorage())
    phoneLanguages(['zh-CN'], 'zh-CN')

    expect(initialLocale()).toBe('zh-Hans')
  })

  it('falls back to navigator.language where languages is absent', () => {
    // Some in-app WebViews omit it — the same environments that force this app
    // to optional-chain navigator.clipboard.
    phoneLanguages(undefined, 'zh-HK')

    expect(initialLocale()).toBe('zh-Hant')
  })
})

describe('applyLocale', () => {
  it('sets the lang attribute that decides glyph forms', () => {
    applyLocale('zh-Hant')
    expect(document.documentElement.lang).toBe('zh-Hant')

    applyLocale('zh-Hans')
    expect(document.documentElement.lang).toBe('zh-Hans')
  })

  it('sets a title that names no business, in every locale', () => {
    for (const locale of ['en', 'zh-Hant', 'zh-Hans'] as const) {
      applyLocale(locale)

      expect(document.title).toBe(CATALOGS[locale].document.title)
    }
  })
})
