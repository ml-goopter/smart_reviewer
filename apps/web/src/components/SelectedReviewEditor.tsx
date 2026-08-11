import { useFocusOnMount } from '../lib/a11y'
import { useMessages } from '../lib/i18n/context'

/** The editor, and the last screen before Google.
 *
 *  Reset is an icon inside the field rather than a labelled button — it is a
 *  minor action next to Continue, and the accepted design keeps the primary
 *  action alone at the bottom. It carries a visible-on-focus outline and an
 *  accessible name because it has no text.
 */
export function SelectedReviewEditor({
  value,
  originalText,
  leaving,
  onChange,
  onReset,
  onBack,
  onContinue,
}: {
  value: string
  originalText: string
  leaving: boolean
  onChange: (value: string) => void
  onReset: () => void
  onBack: () => void
  onContinue: () => void
}) {
  // The merchant's name is not on this screen, so this is the page's only
  // top-level heading. An h2 here would start the document outline at level 2.
  const heading = useFocusOnMount<HTMLHeadingElement>()
  const messages = useMessages()
  const untouched = value === originalText

  return (
    <>
      <div className="stack">
        <h1 className="question" tabIndex={-1} ref={heading}>
          {messages.editor.heading}
        </h1>
        <p className="lead">{messages.editor.lead}</p>
      </div>

      <div className="field">
        <textarea
          className="textarea"
          aria-label={messages.editor.textareaLabel}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          className="reset"
          type="button"
          aria-label={messages.editor.resetLabel}
          title={messages.editor.resetLabel}
          disabled={untouched}
          onClick={onReset}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polyline points="1 4 1 10 7 10" />
            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
          </svg>
        </button>
      </div>

      {/* Before the tap, not after it. Once the customer has decided to leave
        * they are not reading an interstitial, and Continue is a direct
        * redirect — there is no second screen to put this on. */}
      <p className="lead">
        {value.trim() === '' ? messages.editor.emptyHint : messages.editor.copyHint}
      </p>

      <div className="actions">
        {/* Never disabled for being empty. Clearing the box is how somebody
          * says "I'll write my own", and blocking it would strand them here:
          * this screen has no other way out to Google. An empty review simply
          * skips the copy. */}
        <button className="btn btn--primary" disabled={leaving} onClick={onContinue}>
          {leaving ? messages.editor.opening : messages.editor.continue}
        </button>
      </div>

      {/* Without this the first tap on a card is irreversible for the life of
        * the tab: the draft is restored on every load, so returning from Google
        * — or simply reloading — puts the customer back here with the other
        * cards, and any unspent generations, permanently out of reach. */}
      <div className="own">
        <button className="link" onClick={onBack} disabled={leaving}>
          {messages.editor.back}
        </button>
      </div>

      <p className="authenticity">{messages.editor.authenticity}</p>
    </>
  )
}
