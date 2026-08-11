import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LOCALE_NAMES } from '../lib/i18n'
import { LocaleProvider } from '../lib/i18n/context'
import { memoryStorage } from '../lib/testing/memoryStorage'
import { TopBar } from './TopBar'

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  document.documentElement.lang = 'en'
})

function mount(initial: 'en' | 'zh-Hant' | 'zh-Hans' = 'en') {
  render(
    <LocaleProvider initial={initial}>
      <TopBar />
    </LocaleProvider>,
  )
}

/** By class, not by accessible name: the name is itself translated, and these
 *  tests open the drawer in every locale. */
function openDrawer() {
  fireEvent.click(document.querySelector('.menu')!)
}

describe('the drawer', () => {
  it('starts closed', () => {
    mount()

    expect(screen.getByRole('button', { name: 'Menu' }).getAttribute('aria-expanded')).toBe(
      'false',
    )
    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
  })

  it('opens on the hamburger and moves focus into itself', () => {
    mount()
    openDrawer()

    expect(document.querySelector('.drawer')?.className).toContain('drawer--open')
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Close menu' }),
    )
  })

  it('closes on Escape', () => {
    mount()
    openDrawer()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
  })

  it('closes on the scrim', () => {
    mount()
    openDrawer()

    fireEvent.click(document.querySelector('.scrim')!)

    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
  })

  it('lists every language in its own script', () => {
    mount()
    openDrawer()

    for (const name of Object.values(LOCALE_NAMES)) {
      expect(screen.getByRole('menuitemradio', { name })).toBeTruthy()
    }
  })

  it('marks exactly the current language as checked', () => {
    mount('zh-Hant')
    openDrawer()

    const checked = screen
      .getAllByRole('menuitemradio')
      .filter((row) => row.getAttribute('aria-checked') === 'true')

    expect(checked).toHaveLength(1)
    expect(checked[0]!.textContent).toContain(LOCALE_NAMES['zh-Hant'])
  })

  it('switches the language and closes', () => {
    mount('en')
    openDrawer()

    fireEvent.click(screen.getByRole('menuitemradio', { name: LOCALE_NAMES['zh-Hans'] }))

    expect(document.documentElement.lang).toBe('zh-Hans')
    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
  })

  it('closes when the language already on screen is tapped', () => {
    // A no-op that still has to dismiss the drawer, or the tap reads as broken.
    mount('en')
    openDrawer()

    fireEvent.click(screen.getByRole('menuitemradio', { name: LOCALE_NAMES.en }))

    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
    expect(document.documentElement.lang).toBe('en')
  })

  it('translates its own chrome', () => {
    mount('zh-Hant')

    expect(screen.getByRole('button', { name: '選單' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '選單' }))

    expect(screen.getByText('語言')).toBeTruthy()
    expect(screen.getByRole('button', { name: '關閉選單' })).toBeTruthy()
  })

  it('stops listening for Escape once closed', () => {
    // The listener is on the document, so leaving it bound would swallow
    // Escape for anything else on the page.
    mount()
    openDrawer()
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(() => fireEvent.keyDown(document, { key: 'Escape' })).not.toThrow()
    expect(document.querySelector('.drawer')?.className).not.toContain('drawer--open')
  })
})
