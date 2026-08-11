import { useFocusOnMount } from '../lib/a11y'
import { useMessages } from '../lib/i18n/context'
import { TopBar } from './TopBar'

/* The screens with no merchant on them.
 *
 * None of these says why. Which of expired, disabled, unknown, or
 * merchant-deactivated applied is the merchant's private information, and the
 * customer can act on none of them — the only useful instruction is the one
 * that gets them a working session, which is to scan again.
 */

export function LoadingState() {
  const messages = useMessages()

  return (
    <main className="app app--center">
      <div className="brand brand--lg">Goopter</div>
      <div className="spinner" role="status" aria-label={messages.loading.label} />
      <p className="sub">{messages.loading.text}</p>
    </main>
  )
}

/** Three terminal reasons, three pieces of advice — because the useful next
 *  action genuinely differs, not because the customer is owed a diagnosis.
 *
 *  `link`    the merchant cannot be reviewed at all; only they can fix it.
 *  `session` the token is dead, but the permanent QR mints a fresh one.
 *  `busy`    the per-IP creation limit, which clears on its own.
 */
export function UnavailableState({ reason }: { reason: 'link' | 'session' | 'busy' }) {
  // A heading, not a paragraph: §49 says to move focus to the new heading, and
  // these screens have no other text to structure the document around.
  const heading = useFocusOnMount<HTMLHeadingElement>()
  const copy = useMessages().unavailable[reason]

  return (
    <main className="app app--center">
      {/* The instruction below is the whole point of this screen, so it has to
        * be readable — a customer who cannot read it just leaves. */}
      <TopBar />
      <h1 className="message" tabIndex={-1} ref={heading}>
        {copy.message}
      </h1>
      <p className="sub">{copy.advice}</p>
    </main>
  )
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  const heading = useFocusOnMount<HTMLHeadingElement>()
  const messages = useMessages()

  return (
    <main className="app app--center">
      <TopBar />
      <h1 className="message" tabIndex={-1} ref={heading}>
        {messages.error.message}
      </h1>
      <p className="sub">{messages.error.advice}</p>
      <button className="btn btn--primary" style={{ maxWidth: 280 }} onClick={onRetry}>
        {messages.error.retry}
      </button>
    </main>
  )
}
