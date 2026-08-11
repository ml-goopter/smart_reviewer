/* The source catalogue, and the only place a message is written in English.
 *
 * Every other locale is declared as `Messages`, which is `typeof en` — so a
 * locale file that drops a key, invents one, or turns a count function into a
 * plain string fails `tsc --noEmit`, which `npm run build` runs. Nothing is
 * ever looked up by a key assembled at runtime, so there is no missing-message
 * fallback to design and no reason for a lookup to return undefined.
 *
 * Customer-facing screens only. The lead crawler under /leads is an internal
 * tool that only the operator ever sees and stays in English.
 *
 * The two count-bearing entries are functions rather than strings with a
 * placeholder: English needs a plural form here and Chinese has none, and one
 * shared "{count} suggestions" template cannot express that without a
 * plural-rules engine.
 */

export const en = {
  document: {
    /* Deliberately generic in every locale, for the reason index.html states:
     * the tab title and browser history must not record which business was
     * visited. */
    title: 'Write a review',
  },

  loading: {
    /** Accessible name of the spinner, which has no text of its own. */
    label: 'Preparing your review',
    text: 'Preparing your review…',
  },

  /* Three terminal reasons, three pieces of advice. None of them says why —
   * see the note in components/states.tsx. */
  unavailable: {
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
  },

  error: {
    message: 'Something went wrong.',
    advice: 'Please try again.',
    retry: 'Try again',
  },

  /* Live-region text. Read aloud and never seen, so each one has to stand on
   * its own — a screen reader user has no surrounding screen to read it
   * against. */
  announce: {
    generating: 'Writing suggestions…',
    ready: (count: number) => `${count} suggestion${count === 1 ? '' : 's'} ready.`,
    added: (count: number) =>
      `${count} more suggestion${count === 1 ? '' : 's'} added below.`,
    generateFailed: "We couldn't generate new suggestions right now.",
    opening: 'Opening Google.',
  },

  suggestions: {
    heading: 'How was your experience?',
    lead: 'Here are a few ideas to help you write your review.',
    generating: 'Generating…',
    generateMore: 'Generate more suggestions',
    ownHint: 'Prefer to write your own?',
    skip: 'Continue to Google →',
    authenticity:
      'Only use wording that reflects your genuine experience. You can edit any suggestion before posting.',
  },

  card: {
    use: 'Use this review',
  },

  /* The drawer. Its language rows are not here — each language is written in
   * its own script and never translated, so they live in LOCALE_NAMES. */
  menu: {
    open: 'Menu',
    title: 'Menu',
    close: 'Close menu',
    language: 'Language',
  },

  notice: {
    /** The generation cap, with cards already on screen.
     *
     *  Names the language because the cap is per-language: this one is spent,
     *  another is not. It does not say so, though — the cap is a cost control,
     *  and copy that pointed at the menu would market three more paid
     *  generations to everyone who hit it. Every catalogue names its own
     *  language, so nothing is interpolated: the notice always renders in the
     *  locale whose cap was reached. */
    capReached: "You've reached the limit for new English suggestions.",
    /** The same cap reached having seen nothing — the attempts ceiling is
     *  never refunded, so this is reachable against a dead provider. */
    capReachedEmpty: "We couldn't prepare suggestions for you this time.",
    failed: "We couldn't generate new suggestions right now.",
    retry: 'Try again',
    writeOwn: 'Write your own on Google →',
  },

  editor: {
    heading: 'Make it your own',
    lead: 'You can edit this suggestion before continuing to Google.',
    textareaLabel: 'Your review',
    /** Both the accessible name and the tooltip of the icon-only reset. */
    resetLabel: 'Reset to the original suggestion',
    emptyHint: 'Nothing will be copied — you can write your review on Google.',
    copyHint:
      "We'll copy your review and open Google. Paste it into the review box, add your star rating, and post.",
    opening: 'Opening Google…',
    continue: 'Continue to Google Reviews',
    back: '← Choose a different suggestion',
    authenticity: 'Only use wording that reflects your genuine experience.',
  },
}

export type Messages = typeof en
