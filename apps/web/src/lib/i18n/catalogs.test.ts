import { describe, expect, it } from 'vitest'

import { CATALOGS, LOCALES, LOCALE_NAMES, type Locale } from './index'
import { en } from './en'

/* `tsc` already rejects a locale that misses a key — but `npm test` does not
 * run `tsc`, and a catalogue is exactly the kind of file that gets edited by
 * somebody running only the tests. These assert the same guarantees at
 * runtime, plus the two `tsc` cannot see: an entry left empty, and a count
 * function that drops the number it was handed.
 */

/** Every leaf as `path:kind`, so a missing key, an extra key, and a function
 *  swapped for a string are all one comparison. */
function shape(value: unknown, path = ''): string[] {
  if (typeof value === 'object' && value !== null) {
    return Object.entries(value as Record<string, unknown>)
      .flatMap(([key, child]) => shape(child, path === '' ? key : `${path}.${key}`))
      .sort()
  }

  return [`${path}:${typeof value}`]
}

function leaves(value: unknown, path = ''): Array<[string, unknown]> {
  if (typeof value === 'object' && value !== null) {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
      leaves(child, path === '' ? key : `${path}.${key}`),
    )
  }

  return [[path, value]]
}

const OTHERS = LOCALES.filter((locale) => locale !== 'en')

describe('catalogues', () => {
  it.each(OTHERS)('%s has exactly the keys en has', (locale) => {
    expect(shape(CATALOGS[locale])).toEqual(shape(en))
  })

  it.each(LOCALES)('%s has no empty message', (locale) => {
    const empty = leaves(CATALOGS[locale])
      .filter(([, value]) => typeof value === 'string' && value.trim() === '')
      .map(([path]) => path)

    expect(empty).toEqual([])
  })

  it.each(LOCALES)('%s renders the count it is given', (locale) => {
    const { announce } = CATALOGS[locale]

    expect(announce.ready(3)).toContain('3')
    expect(announce.added(2)).toContain('2')
  })

  it('pluralises in English and not in Chinese', () => {
    expect(en.announce.ready(1)).toBe('1 suggestion ready.')
    expect(en.announce.ready(2)).toBe('2 suggestions ready.')

    // The same sentence either side of the count in both Chinese locales —
    // the guard against somebody adding an English-shaped plural rule here.
    for (const locale of ['zh-Hant', 'zh-Hans'] satisfies Locale[]) {
      const { ready } = CATALOGS[locale].announce
      expect(ready(1).replace('1', '')).toBe(ready(2).replace('2', ''))
    }
  })

  it('names every locale in its own language', () => {
    expect(Object.keys(LOCALE_NAMES).sort()).toEqual([...LOCALES].sort())
  })
})
