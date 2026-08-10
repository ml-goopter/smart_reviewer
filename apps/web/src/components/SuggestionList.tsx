import type { FailureKind, Suggestion } from '../lib/types'

/* AI output is rendered as text children only. There is no
 * dangerouslySetInnerHTML anywhere in this app, and this is the component that
 * would be tempted by it. */

function Skeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <div className="skeleton__line" />
      <div className="skeleton__line" />
      <div className="skeleton__line" />
    </div>
  )
}

/** Shown while the first batch is generating.
 *
 *  Not an edge case: GET /sessions/:token never generates, so the very first
 *  render always has zero suggestions and a provider call in flight. Cards
 *  rather than a spinner, because the merchant's name is already on screen and
 *  the shape of what is coming is the useful signal.
 */
export function SuggestionSkeletons() {
  return (
    <div className="cards">
      <Skeleton />
      <Skeleton />
      <Skeleton />
    </div>
  )
}

export function SuggestionCard({
  suggestion,
  onSelect,
}: {
  suggestion: Suggestion
  onSelect: (suggestion: Suggestion) => void
}) {
  return (
    <article className="card">
      <p className="card__text">{suggestion.text}</p>
      {/* Never disabled while a generation runs. §19 asks for existing
        * suggestions to stay usable, and a provider call can take 20s twice
        * over — a customer who already likes card two should not have to wait
        * out a batch they asked for out of curiosity. */}
      <button className="btn btn--primary" onClick={() => onSelect(suggestion)}>
        Use this review
      </button>
    </article>
  )
}

/** Generation failed, but the customer keeps everything they already had.
 *
 *  An optional action must never destroy finished work: by the time Generate
 *  More is pressed there may be three usable suggestions on screen, and the
 *  Google URL has been in hand since the session loaded. This renders inline
 *  above the cards rather than replacing the tree.
 */
export function GenerationNotice({
  kind,
  hasSuggestions,
  onRetry,
  onSkip,
}: {
  kind: FailureKind
  /** Changes the wording, not the controls. "You've reached the limit for new
   *  suggestions" is nonsense to somebody who has never seen one — reachable
   *  because the attempts ceiling (R6a) is never refunded, so a customer
   *  reloading against a dead provider exhausts it having seen nothing. */
  hasSuggestions: boolean
  onRetry: () => void
  onSkip: () => void
}) {
  // 429 is the generation cap — retrying cannot succeed, so it is not offered.
  const exhausted = kind === 'rate-limited'

  const text = exhausted
    ? hasSuggestions
      ? "You've reached the limit for new suggestions."
      : "We couldn't prepare suggestions for you this time."
    : "We couldn't generate new suggestions right now."

  return (
    <div className="notice">
      <p className="notice__text">{text}</p>

      {!exhausted && (
        <button className="btn btn--line" onClick={onRetry}>
          Try again
        </button>
      )}

      {/* AI availability must never be what stops someone reviewing. Redundant
        * once cards exist — the skip link below the list says the same thing —
        * so it only appears when this notice is the whole screen. */}
      {!hasSuggestions && (
        <button className="link" onClick={onSkip}>
          Write your own on Google →
        </button>
      )}
    </div>
  )
}
