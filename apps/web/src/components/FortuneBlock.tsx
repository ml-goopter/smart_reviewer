import type { Fortune } from '../lib/fortunes'
import { useLocale, useMessages } from '../lib/i18n/context'

/* A fortune, above the suggestion list.
 *
 * A real <h2>, not a styled div: the header is visible, so a band that looked
 * titled to a sighted customer and arrived as a loose string everywhere else
 * would be the lie. It costs one stop when navigating by heading, ahead of the
 * question — that is what the screen now is.
 *
 * Still not focused and still not announced. Suggestions moves focus past this
 * to the question heading: the customer scanned a QR code to write a review,
 * and a garnish must not stand between them and the reason they came.
 *
 * Takes the whole entry rather than a string: the draw belongs to Reviewer,
 * which outlives the locale-keyed remount, so this only picks the language.
 */
export function FortuneBlock({ fortune }: { fortune: Fortune }) {
  const { locale } = useLocale()
  const messages = useMessages()

  return (
    <>
      <h2 className="fortune__heading">{messages.fortune.heading}</h2>
      <div className="fortune">
        <p className="fortune__text">{fortune[locale]}</p>
      </div>
    </>
  )
}
