import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { applyLocale, initialLocale, storeLocale } from '../locale'
import { CATALOGS, type Locale, type Messages } from './index'

/* The current locale, and the catalogue that goes with it.
 *
 * Deliberately knows nothing about suggestions, drafts, or generation. A
 * language change has consequences for all three, but they belong to the
 * screen that owns that state — putting them here would make a context
 * provider reach into the reviewer's lifecycle from above it.
 */

type LocaleValue = {
  locale: Locale
  messages: Messages
  setLocale: (locale: Locale) => void
}

const LocaleContext = createContext<LocaleValue | null>(null)

export function LocaleProvider({
  children,
  initial,
}: {
  children: ReactNode
  /** Skips detection. Only for tests, which would otherwise have to stub both
   *  localStorage and navigator to render a screen in Chinese. */
  initial?: Locale
}) {
  const [locale, setCurrent] = useState<Locale>(initial ?? initialLocale)

  // Layout effect, not a plain one: `lang` decides which glyph forms the text
  // is drawn with, and applying it after paint would show the first frame in
  // the wrong script.
  useLayoutEffect(() => {
    applyLocale(locale)
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    // Persisted before the render, for the same reason draft.ts persists on
    // every keystroke: the customer leaves this page by assignment to
    // window.location, and there is no reliable unload hook to catch.
    storeLocale(next)
    setCurrent(next)
  }, [])

  const value = useMemo(
    () => ({ locale, messages: CATALOGS[locale], setLocale }),
    [locale, setLocale],
  )

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleValue {
  const value = useContext(LocaleContext)

  // Thrown, not defaulted to English. A screen rendered outside the provider
  // is a wiring mistake, and quietly serving English would hide it behind copy
  // that looks deliberate.
  if (value === null) {
    throw new Error('useLocale must be used inside a LocaleProvider')
  }

  return value
}

export function useMessages(): Messages {
  return useLocale().messages
}
