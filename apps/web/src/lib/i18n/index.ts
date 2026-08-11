import { en } from './en'
import { zhHans } from './zh-Hans'
import { zhHant } from './zh-Hant'

import type { Messages } from './en'

/* The locale set, and the catalogue for each.
 *
 * Nothing here reads the browser, stores a preference, or renders — this
 * module is only the message data, so a component can be given a catalogue in
 * a test without a detection ladder standing between the two.
 */

export type { Messages } from './en'

/** Every code is a BCP-47 tag, so it can be written straight into
 *  `document.documentElement.lang`. That attribute is not decorative for these
 *  two: a browser picks Traditional or Simplified glyph forms for the same
 *  codepoint from it, and without it one of the two renders in the other's
 *  shapes. */
export const LOCALES = ['en', 'zh-Hant', 'zh-Hans'] as const

export type Locale = (typeof LOCALES)[number]

export const CATALOGS: Record<Locale, Messages> = {
  en,
  'zh-Hant': zhHant,
  'zh-Hans': zhHans,
}

/** Each locale's name in its own language. Never translated: somebody looking
 *  for Chinese in an English UI is looking for 中文, not for the word
 *  "Chinese" rendered in a script they are trying to leave. */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: 'English',
  'zh-Hant': '繁體中文',
  'zh-Hans': '简体中文',
}
