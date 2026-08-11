import { useCallback, useEffect, useRef, useState } from 'react'

import { LOCALES, LOCALE_NAMES, type Locale } from '../lib/i18n'
import { useLocale, useMessages } from '../lib/i18n/context'

/* The wordmark and the way into the language menu.
 *
 * Present on every customer-facing screen except loading — including the
 * terminal ones, where the instruction ("scan the QR code again") is the whole
 * point and a customer who cannot read it simply leaves.
 *
 * Geometry follows mockups/smart-reviewer-counter.html.
 */

export function TopBar() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <div className="topbar">
        <span className="topbar__wordmark">Goopter</span>
        <MenuButton expanded={open} onOpen={() => setOpen(true)} />
      </div>

      <Drawer open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function MenuButton({ expanded, onOpen }: { expanded: boolean; onOpen: () => void }) {
  const messages = useMessages()

  return (
    <button
      className="menu"
      type="button"
      aria-label={messages.menu.open}
      aria-haspopup="menu"
      aria-expanded={expanded}
      onClick={onOpen}
    >
      {/* 文 over A — the translate mark. The drawer behind it holds nothing
        * but the language choice, and this names the choice on offer where
        * three bars promised a menu that does not exist. Type rather than
        * strokes, so both glyphs come from the app's own faces: sizing and
        * the :lang(zh-Hant) swap live on .menu__han / .menu__latin. */}
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <text className="menu__han" x="7" y="12" textAnchor="middle">
          文
        </text>
        <text className="menu__latin" x="17.5" y="22.5" textAnchor="middle">
          A
        </text>
      </svg>
    </button>
  )
}

function Drawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const messages = useMessages()
  const { locale, setLocale } = useLocale()
  const closeRef = useRef<HTMLButtonElement>(null)

  /* Focus moves into the drawer when it opens and back to nothing in
   * particular when it closes — the screen behind is replaced on a language
   * change, and Reviewer moves focus to its heading for that. */
  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  /* Escape is listened for on the document rather than on the panel: the
   * drawer is closed by tapping the scrim too, and a keydown handler bound to
   * the panel only fires while focus is still inside it. */
  useEffect(() => {
    if (!open) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  const choose = useCallback(
    (next: Locale) => {
      // Closed either way. Picking the language already on screen is a no-op
      // that still has to dismiss the drawer, or the tap reads as broken.
      onClose()
      if (next !== locale) setLocale(next)
    },
    [locale, onClose, setLocale],
  )

  return (
    <>
      {/* Rendered even while closed so the transform transition has something
        * to animate from; `visibility` in the stylesheet is what keeps it out
        * of the accessibility tree and off the tab order. */}
      <div
        className={open ? 'scrim scrim--open' : 'scrim'}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={open ? 'drawer drawer--open' : 'drawer'}
        aria-label={messages.menu.title}
        aria-hidden={!open}
      >
        <div className="drawer__head">
          <span className="drawer__title">{messages.menu.title}</span>
          <button
            className="drawer__close"
            type="button"
            ref={closeRef}
            aria-label={messages.menu.close}
            onClick={onClose}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <line x1="6" y1="6" x2="18" y2="18" />
              <line x1="18" y1="6" x2="6" y2="18" />
            </svg>
          </button>
        </div>

        <div className="drawer__label">{messages.menu.language}</div>

        {/* menuitemradio, not a native radio group: exactly one is chosen, and
          * the choice takes effect on the tap rather than on a submit. */}
        <div role="menu" aria-label={messages.menu.language}>
          {LOCALES.map((option) => (
            <button
              key={option}
              className="lang"
              type="button"
              role="menuitemradio"
              aria-checked={option === locale}
              onClick={() => choose(option)}
            >
              {/* Never translated: somebody looking for Chinese in an English
                * UI is looking for 中文, not for the word "Chinese". */}
              <span>{LOCALE_NAMES[option]}</span>
              <svg
                className="lang__tick"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </button>
          ))}
        </div>
      </aside>
    </>
  )
}
