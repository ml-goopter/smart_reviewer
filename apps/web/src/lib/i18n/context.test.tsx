import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { memoryStorage, throwingStorage } from '../testing/memoryStorage'
import { LocaleProvider, useLocale, useMessages } from './context'
import type { Locale } from './index'

const OPTIONS = ['en', 'zh-Hant', 'zh-Hans'] satisfies Locale[]

/** jsdom has no localStorage, so every test supplies one. */
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.lang = 'en'
})

function Screen() {
  const { locale, setLocale } = useLocale()
  const messages = useMessages()

  return (
    <div>
      <p>{messages.suggestions.heading}</p>
      <span data-testid="locale">{locale}</span>
      {OPTIONS.map((option) => (
        <button key={option} onClick={() => setLocale(option)}>
          {option}
        </button>
      ))}
    </div>
  )
}

describe('LocaleProvider', () => {
  it('renders the catalogue for the initial locale', () => {
    render(
      <LocaleProvider initial="zh-Hant">
        <Screen />
      </LocaleProvider>,
    )

    expect(screen.getByText('這次的體驗如何？')).toBeTruthy()
  })

  it('swaps the whole catalogue when the locale changes', () => {
    render(
      <LocaleProvider initial="en">
        <Screen />
      </LocaleProvider>,
    )

    expect(screen.getByText('How was your experience?')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'zh-Hans' }))

    expect(screen.getByText('这次的体验如何？')).toBeTruthy()
    expect(screen.getByTestId('locale').textContent).toBe('zh-Hans')
  })

  it('applies lang and title on mount and on every change', () => {
    render(
      <LocaleProvider initial="zh-Hant">
        <Screen />
      </LocaleProvider>,
    )

    expect(document.documentElement.lang).toBe('zh-Hant')
    expect(document.title).toBe('撰寫評論')

    fireEvent.click(screen.getByRole('button', { name: 'zh-Hans' }))

    // The two Chinese locales share codepoints; only this attribute tells the
    // browser which script's glyph forms to draw.
    expect(document.documentElement.lang).toBe('zh-Hans')
    expect(document.title).toBe('撰写评价')
  })

  it('persists the choice so the next scan starts there', () => {
    render(
      <LocaleProvider initial="en">
        <Screen />
      </LocaleProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'zh-Hant' }))

    expect(localStorage.getItem('smart-reviewer:locale')).toBe('zh-Hant')
  })

  it('detects when given no initial locale', () => {
    vi.spyOn(Navigator.prototype, 'languages', 'get').mockReturnValue(['zh-HK', 'en'])

    render(
      <LocaleProvider>
        <Screen />
      </LocaleProvider>,
    )

    expect(screen.getByTestId('locale').textContent).toBe('zh-Hant')
  })

  it('still switches when storage is unavailable', () => {
    vi.stubGlobal('localStorage', throwingStorage())

    render(
      <LocaleProvider initial="en">
        <Screen />
      </LocaleProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'zh-Hant' }))

    // The choice applies to the page in front of the customer even though it
    // cannot outlive it.
    expect(screen.getByText('這次的體驗如何？')).toBeTruthy()
  })
})

describe('useLocale', () => {
  it('throws outside a provider rather than quietly serving English', () => {
    // React logs the error it re-throws; the assertion is what matters.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => render(<Screen />)).toThrow(/LocaleProvider/)

    consoleError.mockRestore()
  })
})
