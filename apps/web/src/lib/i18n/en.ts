/* The source catalogue, and the only place a message is written in English.
 *
 * Every other locale is declared as `Messages`, which is `typeof en` — so a
 * locale file that drops a key, invents one, or turns a count function into a
 * plain string fails `tsc --noEmit`, which `npm run build` runs. Nothing is
 * ever looked up by a key assembled at runtime, so there is no missing-message
 * fallback to design and no reason for a lookup to return undefined.
 *
 * Customer-facing screens and the internal lead crawler under /leads. The
 * crawler is kept in its own `leads` namespace: it shares the language choice
 * and the drawer that makes it, and nothing else.
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
    skip: 'Write your own',
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
    capReached: "You've reached the limit for new suggestions.",
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

  /* The internal lead crawler under /leads.
   *
   * Translated for the same reason the customer screens are: the operator
   * prospecting Chinese-speaking merchants is as likely to read Chinese as
   * they are. Nothing here is customer-facing, so the register is the
   * operator's — terse, and it keeps the words the API and Google use.
   *
   * Merchant names, addresses, slugs and statuses stay as the server sent
   * them. They are data, not copy. */
  leads: {
    title: 'Lead crawler',
    viewsLabel: 'Lead crawler views',
    tabs: {
      search: 'Search',
      saved: 'Saved',
    },
    loading: 'Loading…',
    edit: 'Edit',
    copyUrl: 'Copy URL',
    /** Reads as a fragment because it follows the merchant's status: an
     *  archived row has no working URL to copy. */
    noUrl: 'no URL',

    /** Keyed by the value the server sends rather than by its label, so the
     *  server stays the authority on which categories exist. One it adds
     *  before this list catches up falls back to the English label it sent,
     *  which is better than an option that renders blank. */
    categories: {
      restaurant: 'Restaurant',
      cafe: 'Cafe',
      bar: 'Bar',
      bakery: 'Bakery',
      meal_takeaway: 'Takeout',
      hair_salon: 'Hair salon',
      nail_salon: 'Nail salon',
      spa: 'Spa',
      gym: 'Gym',
      dentist: 'Dentist',
      car_repair: 'Auto repair',
      florist: 'Florist',
      pet_store: 'Pet store',
      book_store: 'Book store',
    },

    /* Keyed by the machine-readable `error` the API returns. Unlike the
     * customer-facing screens — which decide from the status code alone so a
     * private cause cannot leak — this is an internal tool, and the operator
     * is the person who has to act on the distinction. */
    failures: {
      criteria_too_broad:
        'Add a category or a text query — a location alone does not say what to look for.',
      location_not_found: 'Google does not recognise that location. Check the spelling.',
      unknown_category: 'That category is not one the server accepts.',
      invalid_rating_range: 'The minimum rating is above the maximum.',
      invalid_request: 'Some criteria are out of range.',
      provider_unavailable: 'Google did not answer. Try again in a moment.',
      network: 'Could not reach the API.',
      /** A code this build has no copy for. The status is included because the
       *  operator can act on it and there is no customer to protect. */
      status: (status: number) => `Request failed (${status}).`,
      unknown: 'Something went wrong.',
    },

    search: {
      location: 'Location',
      locationPlaceholder: 'Postal code, city or address',
      radius: 'Radius (m)',
      category: 'Category',
      anyCategory: 'Any',
      textQuery: 'Text query',
      textQueryPlaceholder: 'Sushi Mura omakase',
      ratingMin: 'Rating min',
      ratingMax: 'Rating max',
      maxReviews: 'Max reviews',
      submit: 'Search',
      submitting: 'Searching…',
      /** Stated up front rather than only after a refusal: the requirement is
       *  not guessable from a form whose only required field is the location. */
      note: 'A category or a text query is required — the location says where to look, not what for.',
      /* Split so the geocoded place can stay emphasised — it is the one
       * thing the operator checks to confirm Google understood the query —
       * while each language keeps its own word order around it. */
      resolvedBefore: 'Searched around ',
      resolvedAfter: '.',
      funnel: (searched: number, matched: number) =>
        `${searched} listings searched · ${matched} matched`,
      partial: 'Google returned an error partway through — these results are incomplete.',
      truncated:
        'Stopped at the result ceiling — Google had more. Narrow the search or raise LEAD_SEARCH_MAX_RESULTS.',
      empty:
        'Nothing matched. The rating and review-count limits are applied after Google returns its listings, so a tight cap can empty the list.',
      merchant: 'Merchant',
      rating: 'Rating',
      reviews: 'Reviews',
      distance: 'Distance',
      /** The cell under it. A row of "1.2 km" under 距離 is the one place the
       *  table was still half-English. */
      metres: (value: number) => `${value} m`,
      kilometres: (value: string) => `${value} km`,
      uncategorised: 'Uncategorised',
      website: 'Website',
      savedBadge: 'Saved',
      save: 'Save',
      saving: 'Saving…',
      alreadySaved: (name: string) =>
        `${name} was already saved — the existing row is unchanged.`,
      /** The save found a row whose status means the URL is dead. The server
       *  sends no prose for this: a saved merchant is inert until subscribed,
       *  and the sentence saying so belongs in the locale rather than in an
       *  English string under a Chinese header. */
      notSubscribed: (name: string) =>
        `${name}: not subscribed — this URL will not open until it is`,
    },

    saved: {
      merchant: 'Merchant',
      /** Column header over the subscription state and its last valid day. */
      subscription: 'Subscription',
      /** Column header over the date a merchant was saved. */
      savedOn: 'Saved',
      failed: 'Could not load saved merchants.',
      failedMore: 'Could not load more saved merchants.',
      empty: 'Nothing saved yet. Run a search to add one.',
      loadMore: 'Load more',
      loadingMore: 'Loading…',
    },

    /** Shared: the saved list shows these, the editor acts on them. */
    subscription: {
      heading: 'Subscription',
      /** A merchant that has never been subscribed. Its URL does not open. */
      notSubscribed: 'not subscribed',
      /** Prefixed to the LAST VALID DAY, not to the stored `expiresAt`. That
       *  timestamp is the midnight *starting* the day after, so "Expires 12 Sep"
       *  would promise a day the link does not work. "Expires 11 Sep 2026" is
       *  the true statement: it works all of the 11th and dies at its end.
       *  The year is shown because a term can run past one. */
      expires: 'Expires',
      subscribe: (days: number) => `Subscribe ${days} days`,
      renew: (days: number) => `Renew ${days} days`,
      suspend: 'Suspend',
      resume: 'Resume',
      failed: 'Could not update the subscription.',
      /** Says what Renew will do, because the answer is not "today + N": an
       *  early renewal adds to the days already paid for. */
      renewNote: 'Renewing adds to the days remaining — it never replaces them.',
      /** Renew is offered on a suspended merchant, and does not reopen the URL. */
      suspendedNote: 'Suspended. The term is still running; only Resume reopens the URL.',
    },

    copy: {
      copy: 'Copy',
      copied: 'Copied',
      failed: 'Copy failed',
      /** The label changes on the control just pressed, which a screen reader
       *  does not re-announce. These are what it hears instead. */
      copiedAnnouncement: 'Copied to clipboard',
      failedAnnouncement: 'Copy failed — select the URL and copy it by hand',
    },

    editor: {
      back: '← Back',
      reviews: 'reviews',
      asOf: (date: string) => `(as of ${date})`,
      note: 'Google supplies the summary and the attributes. Everything else here is what it cannot know — and together they are the whole of what the AI is told about this merchant.',
      about: 'About the business',
      /* Grouped by the question each field answers, because eight textareas in
       * one column read as a form to get through rather than a description to
       * write. */
      offers: {
        title: 'What it offers',
        caption: 'This is what makes a review sound like a real visit.',
      },
      voice: {
        title: 'How reviews should read',
        caption: 'The angles a suggestion is written from, and the words it may use.',
      },
      instruction: {
        title: 'Agent Instruction',
      },
      /* A field carries a hint only where one earns its place. Three of these
       * are the fields Google cannot answer, which is the reason this screen
       * exists, and their labels already say it. */
      fields: {
        businessSummary: {
          label: 'Business summary',
          hint: 'What the business is, in two or three specific sentences. Prefilled from Google’s editorial line, or a plain sentence built from the category and city when Google had none.',
        },
        products: { label: 'Products' },
        services: { label: 'Services' },
        menuItems: { label: 'Menu items' },
        sellingPoints: {
          label: 'Selling points',
          hint: 'What regulars actually praise. Prefilled from Google’s attributes (dine-in, takeout) — those are true of everyone, so replace them with what makes this place different.',
        },
        approvedKeywords: {
          label: 'Approved keywords',
          hint: 'Words the merchant is happy to see in a review. Offered to the model, never forced into it.',
        },
        experienceTopics: {
          label: 'Experience topics',
          hint: 'One angle per suggestion, rotating each batch, so three cards read as different reviews. Prefilled from the business category.',
        },
        customInstructions: {
          label: 'Custom instructions',
          hint: 'Let the agent know about custom rules / style the reviews should adopt. Do not tell the agent to include links, this would break output validation',
        },
      },
      onePerLine: 'One per line',
      noLinks: 'No links or web addresses',
      save: 'Save context',
      saving: 'Saving…',
      saved: 'Saved',
      confirmation: 'All eight fields replaced.',
      loadFailed: 'Could not load this merchant.',
      saveFailed: 'Could not save.',
      linkRejected:
        'Custom instructions cannot contain a link or web address — generated reviews reject URLs, so every suggestion for this merchant would fail.',
    },
  },
}

export type Messages = typeof en
