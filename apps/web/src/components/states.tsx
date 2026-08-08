import { useFocusOnMount } from '../lib/a11y'

/* The screens with no merchant on them.
 *
 * None of these says why. Which of expired, disabled, unknown, or
 * merchant-deactivated applied is the merchant's private information, and the
 * customer can act on none of them — the only useful instruction is the one
 * that gets them a working session, which is to scan again.
 */

export function LoadingState() {
  return (
    <main className="app app--center">
      <div className="brand brand--lg">Goopter</div>
      <div className="spinner" role="status" aria-label="Preparing your review" />
      <p className="sub">Preparing your review…</p>
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

  const copy = {
    link: {
      message: 'This review link is no longer available.',
      advice: 'Please ask the business for assistance.',
    },
    session: {
      message: 'This review session is no longer available.',
      advice: "Please scan the business's review QR code again.",
    },
    busy: {
      message: 'This review link is busy right now.',
      advice: 'Please scan the QR code again in a few minutes.',
    },
  }[reason]

  return (
    <main className="app app--center">
      <div className="brand">Goopter</div>
      <h1 className="message" tabIndex={-1} ref={heading}>
        {copy.message}
      </h1>
      <p className="sub">{copy.advice}</p>
    </main>
  )
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  const heading = useFocusOnMount<HTMLHeadingElement>()

  return (
    <main className="app app--center">
      <div className="brand">Goopter</div>
      <h1 className="message" tabIndex={-1} ref={heading}>
        Something went wrong.
      </h1>
      <p className="sub">Please try again.</p>
      <button className="btn btn--primary" style={{ maxWidth: 280 }} onClick={onRetry}>
        Try again
      </button>
    </main>
  )
}
