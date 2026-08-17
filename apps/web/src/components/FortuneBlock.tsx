import type { Fortune } from '../lib/fortunes'
import { useLocale } from '../lib/i18n/context'

/* A fortune, above the suggestion list.
 *
 * Ornamental by decision: it is not focused, not announced, and carries no
 * heading. It renders before the <h2> in DOM order so it is reachable in browse
 * mode, but Suggestions still moves focus to that heading — the customer
 * scanned a QR code to write a review, and a garnish must not stand between
 * them and the reason they came.
 *
 * Takes the whole entry rather than a string: the draw belongs to Reviewer,
 * which outlives the locale-keyed remount, so this only picks the language.
 */
export function FortuneBlock({ fortune }: { fortune: Fortune }) {
  const { locale } = useLocale()

  return (
    <div className="fortune">
      <p className="fortune__text">{fortune[locale]}</p>
    </div>
  )
}
