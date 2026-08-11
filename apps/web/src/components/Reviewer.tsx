import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiFailure, completeSession, generateSuggestions, loadSession, selectSuggestion } from '../lib/api'
import { clearDraft, loadDraft, saveDraft } from '../lib/draft'
import { useFocusOnMount } from '../lib/a11y'
import { useLocale, useMessages } from '../lib/i18n/context'
import type { Locale } from '../lib/i18n'
import type { FailureKind, Session, Suggestion } from '../lib/types'
import { ErrorState, LoadingState, UnavailableState } from './states'
import { GenerationNotice, SuggestionCard, SuggestionSkeletons } from './SuggestionList'
import { SelectedReviewEditor } from './SelectedReviewEditor'
import { TopBar } from './TopBar'

type Phase =
  | { name: 'loading' }
  | { name: 'ready'; session: Session }
  | { name: 'gone' }
  | { name: 'error' }

export function Reviewer({ token }: { token: string }) {
  const messages = useMessages()
  const { locale } = useLocale()

  const [phase, setPhase] = useState<Phase>({ name: 'loading' })
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [generating, setGenerating] = useState(false)
  const [genFailure, setGenFailure] = useState<FailureKind | null>(null)
  /* The cap is per language, so this is a list rather than a flag: English
   * being spent says nothing about whether Chinese is. */
  const [cappedLanguages, setCappedLanguages] = useState<Locale[]>([])

  const [editing, setEditing] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [originalText, setOriginalText] = useState('')
  const [reviewText, setReviewText] = useState('')

  const [announcement, setAnnouncement] = useState('')

  /* Every generation costs money and one of a few cap slots, so concurrency is
   * guarded by a ref set synchronously before the first await — state would be
   * a render behind, and both Strict Mode's double-invoked effect and an
   * impatient double-tap fire well inside that window. */
  const generatingRef = useRef(false)
  /* Which languages have had their first batch requested. Never cleared, so
   * each language asks exactly once per mount whatever Strict Mode does to
   * the effect around it — and so a language whose generation failed shows
   * its notice rather than retrying on a loop. */
  const requestedRef = useRef<Set<Locale>>(new Set())
  /* The redirect happens once. A second tap would double-count the completion
   * metric and race the navigation. The ref is the guard — it is readable
   * synchronously, before any re-render — and the state is only so the button
   * can show it. */
  const leavingRef = useRef(false)
  const [leaving, setLeaving] = useState(false)

  /* Everything the session holds, in every language, readable synchronously.
   * `generate` is a useCallback keyed on the token, so the `suggestions` it
   * closes over is stale by the time an await resolves. Read rather than
   * counted by hand: the count is now per language, and a hand-maintained
   * counter would have to be kept in step at every place suggestions are
   * set. */
  const suggestionsRef = useRef(suggestions)
  suggestionsRef.current = suggestions

  /* The language to generate in, for the same reason the catalogue is a ref:
   * putting it in `generate`'s dependencies would re-run the session load. */
  const localeRef = useRef(locale)
  localeRef.current = locale

  /* The catalogue, readable synchronously, for the same reason countRef exists:
   * `generate` is keyed on the token alone. Adding the catalogue to its
   * dependencies would change its identity on every language change, and the
   * session-loading effect below depends on `generate` — so switching language
   * would re-run GET /sessions, which is a write (it marks the session opened)
   * and would reset the list. Assigned during render so an announcement made
   * after an await is worded in the language on screen now, not the one that
   * was on screen when the request went out. */
  const messagesRef = useRef(messages)
  messagesRef.current = messages

  const generate = useCallback(async () => {
    if (generatingRef.current) return
    generatingRef.current = true

    // Read once, before the first await. The customer may open the drawer
    // while this is in flight, and the batch that comes back belongs to the
    // language it was asked for — not to whichever is on screen when it lands.
    const language = localeRef.current

    setGenerating(true)
    setGenFailure(null)
    setAnnouncement(messagesRef.current.announce.generating)

    try {
      const batch = await generateSuggestions(token, language)
      const isFirst = !suggestionsRef.current.some(
        (item) => item.language === language,
      )

      // Appended, never replaced. A customer who liked the second card and
      // pressed Generate More could otherwise never get it back, and at the
      // cap would be stuck with whichever batch happened to be last. New cards
      // land at the bottom, directly above the button that was just tapped —
      // prepending would put them off-screen and read as nothing happening.
      setSuggestions((current) => [...current, ...batch.suggestions])

      const added = batch.suggestions.length

      const { announce } = messagesRef.current
      setAnnouncement(isFirst ? announce.ready(added) : announce.added(added))
    } catch (error) {
      const kind = error instanceof ApiFailure ? error.kind : 'server'

      // A dead token is terminal wherever it surfaces; everything else leaves
      // the screen exactly as it was and reports inline.
      if (kind === 'session-gone') {
        setPhase({ name: 'gone' })
      } else {
        if (kind === 'rate-limited') {
          setCappedLanguages((current) =>
            current.includes(language) ? current : [...current, language],
          )
        }
        setGenFailure(kind)
        setAnnouncement(messagesRef.current.announce.generateFailed)
      }
    } finally {
      generatingRef.current = false
      setGenerating(false)
    }
  }, [token])

  useEffect(() => {
    let live = true

    void (async () => {
      try {
        const session = await loadSession(token)
        if (!live) return

        setPhase({ name: 'ready', session })
        setSuggestions(session.suggestions)

        // Restored before anything is generated: a customer returning from
        // Google already has a review, and spending a cap slot to regenerate
        // suggestions they will never see is pure waste. The effect below
        // holds off while `editing` is set, for the same reason.
        const draft = loadDraft(token)
        if (draft && draft.selectedId !== null) {
          setSelectedId(draft.selectedId)
          setOriginalText(draft.originalText)
          setReviewText(draft.reviewText)
          setEditing(true)
        }
      } catch (error) {
        if (!live) return

        const kind = error instanceof ApiFailure ? error.kind : 'server'
        setPhase(kind === 'session-gone' ? { name: 'gone' } : { name: 'error' })
      }
    })()

    return () => {
      live = false
    }
  }, [token])

  /* Switching language returns the customer to the list and drops whatever was
   * selected: the editor holds a suggestion in a language that is no longer on
   * screen, and the list behind it is about to be a different one.
   *
   * Guarded on the previous value rather than skipping a "first run" flag,
   * because Strict Mode mounts effects twice and a flag would burn its skip on
   * the duplicate. */
  const previousLocale = useRef(locale)

  useEffect(() => {
    if (previousLocale.current === locale) return
    previousLocale.current = locale

    backToSuggestions()
    // Belongs to the batch that failed, in a language no longer on screen.
    setGenFailure(null)
  }, [locale])

  /* Whatever language is on screen gets a batch, or a request for one.
   *
   * This is the only place a generation starts on its own, first load and
   * language switch alike — they are the same condition, and writing them
   * separately is how one of them ends up spending a slot the other already
   * spent. GET never generates (R4), so an empty list is the normal first
   * load rather than a failure. */
  useEffect(() => {
    if (phase.name !== 'ready') return
    // The customer has a review in hand; the list behind it can wait until
    // they ask for it.
    if (editing) return
    if (requestedRef.current.has(locale)) return
    if (suggestionsRef.current.some((item) => item.language === locale)) return

    requestedRef.current.add(locale)
    void generate()
  }, [phase.name, locale, editing, generate])

  // Persisted on every edit rather than on leave: `pagehide` is unreliable on
  // iOS, and this is the state the whole back-button guarantee rests on.
  useEffect(() => {
    if (!editing || selectedId === null) return

    saveDraft(token, { selectedId, originalText, reviewText })
  }, [token, editing, selectedId, originalText, reviewText])

  function choose(suggestion: Suggestion) {
    setSelectedId(suggestion.id)
    setOriginalText(suggestion.text)
    setReviewText(suggestion.text)
    setEditing(true)

    // Deliberately not awaited and its failure deliberately ignored: this only
    // records which card was chosen. The editor already holds the text, and
    // blocking it on an analytics write would be a worse product.
    selectSuggestion(token, suggestion.id).catch(() => {})
  }

  function leaveForGoogle(textToCopy: string | null) {
    if (phase.name !== 'ready' || leavingRef.current) return
    leavingRef.current = true

    let reviewCopied = false

    if (textToCopy !== null && textToCopy.trim() !== '') {
      // First statement in the handler and never awaited. Safari honours a
      // clipboard write only while the user gesture is still active, and any
      // await before it — a fetch above all — ends that gesture.
      //
      // `navigator.clipboard` is undefined outside a secure context, so this is
      // optional-chained rather than assumed. A failure is silent by decision
      // (R9c): the customer always reaches Google, and on an insecure origin
      // they arrive without the text.
      try {
        void navigator.clipboard?.writeText(textToCopy).catch(() => {})
        reviewCopied = navigator.clipboard !== undefined
      } catch {
        reviewCopied = false
      }
    }

    completeSession(token, {
      ...(selectedId !== null ? { suggestionId: selectedId } : {}),
      reviewCopied,
    })

    // After the clipboard write and after /complete is queued, so neither waits
    // on a render. If the navigation is refused — some in-app WebViews block a
    // cross-origin assignment — this is also the only thing that tells the
    // customer anything happened at all.
    setLeaving(true)
    setAnnouncement(messages.announce.opening)

    window.location.href = phase.session.googleReviewUrl
  }

  /* Only the language on screen. The session holds every language it has
   * generated in, so switching back to one is a filter rather than a fetch. */
  const visible = suggestions.filter((item) => item.language === locale)

  /** Back to the list. Without this the first tap on a card is irreversible for
   *  the life of the tab: the draft restores on every load, so returning from
   *  Google puts the customer straight back into the editor with the other
   *  cards — and any unspent generations — permanently out of reach. */
  function backToSuggestions() {
    clearDraft(token)
    setEditing(false)
    setSelectedId(null)
    setOriginalText('')
    setReviewText('')
  }

  return (
    <>
      {/* Mounted for the whole life of the page, above every early return
        * below. A live region inserted in the same commit as its first message
        * is usually not announced at all — and phase and the first
        * announcement are set in one React batch, so hosting this inside the
        * ready branch silenced the entire first-batch cycle, which is the only
        * one every customer sees. */}
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>

      {/* Keyed on the locale so a language change remounts the screen, which
        * is what re-runs useFocusOnMount. Every other stage change here is a
        * fresh mount already; without this one, switching language would swap
        * every word on the page and give a screen reader no reason to start
        * reading it. */}
      <Stage
        key={locale}
        phase={phase}
        editing={editing}
        reviewText={reviewText}
        originalText={originalText}
        leaving={leaving}
        suggestions={visible}
        generating={generating}
        genFailure={genFailure}
        capReached={cappedLanguages.includes(locale)}
        onChange={setReviewText}
        onReset={() => setReviewText(originalText)}
        onBack={backToSuggestions}
        onSelect={choose}
        onGenerate={() => void generate()}
        onContinue={() => leaveForGoogle(reviewText)}
        onSkip={() => leaveForGoogle(null)}
      />
    </>
  )
}

function Stage({
  phase,
  editing,
  reviewText,
  originalText,
  leaving,
  suggestions,
  generating,
  genFailure,
  capReached,
  onChange,
  onReset,
  onBack,
  onSelect,
  onGenerate,
  onContinue,
  onSkip,
}: {
  phase: Phase
  editing: boolean
  reviewText: string
  originalText: string
  leaving: boolean
  suggestions: Suggestion[]
  generating: boolean
  genFailure: FailureKind | null
  capReached: boolean
  onChange: (value: string) => void
  onReset: () => void
  onBack: () => void
  onSelect: (suggestion: Suggestion) => void
  onGenerate: () => void
  onContinue: () => void
  onSkip: () => void
}) {
  if (phase.name === 'loading') return <LoadingState />
  if (phase.name === 'gone') return <UnavailableState reason="session" />
  if (phase.name === 'error') return <ErrorState onRetry={() => window.location.reload()} />

  const { merchant } = phase.session

  return (
    <main className="app">
      {editing ? (
        <>
          <TopBar />
          <hr className="divider" />
          <SelectedReviewEditor
            value={reviewText}
            originalText={originalText}
            leaving={leaving}
            onChange={onChange}
            onReset={onReset}
            onBack={onBack}
            onContinue={onContinue}
          />
        </>
      ) : (
        <Suggestions
          merchantName={merchant.name}
          category={merchant.category}
          suggestions={suggestions}
          generating={generating}
          genFailure={genFailure}
          capReached={capReached}
          onSelect={onSelect}
          onGenerate={onGenerate}
          onSkip={onSkip}
        />
      )}
    </main>
  )
}

function Suggestions({
  merchantName,
  category,
  suggestions,
  generating,
  genFailure,
  capReached,
  onSelect,
  onGenerate,
  onSkip,
}: {
  merchantName: string
  category: string | null
  suggestions: Suggestion[]
  generating: boolean
  genFailure: FailureKind | null
  capReached: boolean
  onSelect: (suggestion: Suggestion) => void
  onGenerate: () => void
  onSkip: () => void
}) {
  const heading = useFocusOnMount<HTMLHeadingElement>()
  const messages = useMessages()

  return (
    <>
      <TopBar />

      <div className="stack">
        {/* Merchant name and category are data, not copy — they stay in
          * whatever language the merchant registered them in. */}
        <h1 className="merchant">{merchantName}</h1>
        {category !== null && <div className="category">{category}</div>}
      </div>

      <hr className="divider" />

      <div className="stack">
        <h2 className="question" tabIndex={-1} ref={heading}>
          {messages.suggestions.heading}
        </h2>
        <p className="lead">{messages.suggestions.lead}</p>
      </div>

      {genFailure !== null && (
        <GenerationNotice
          kind={genFailure}
          hasSuggestions={suggestions.length > 0}
          onRetry={onGenerate}
          onSkip={onSkip}
        />
      )}

      {/* Skeletons only when there is nothing to show. A regeneration keeps the
        * existing cards on screen and selectable — see SuggestionCard. */}
      <div className="cards">
        {suggestions.map((suggestion) => (
          <SuggestionCard key={suggestion.id} suggestion={suggestion} onSelect={onSelect} />
        ))}
        {generating && <SuggestionSkeletons />}
      </div>

      {/* Hidden once the cap is reached: an action that cannot succeed is worse
        * than an absent one. Google stays reachable either way. */}
      {!capReached && (
        <button className="btn btn--line" disabled={generating} onClick={onGenerate}>
          {generating ? messages.suggestions.generating : messages.suggestions.generateMore}
        </button>
      )}

      <div className="own">
        <span className="own__hint">{messages.suggestions.ownHint}</span>
        <button className="link" onClick={onSkip}>
          {messages.suggestions.skip}
        </button>
      </div>

      <p className="authenticity">{messages.suggestions.authenticity}</p>
    </>
  )
}
