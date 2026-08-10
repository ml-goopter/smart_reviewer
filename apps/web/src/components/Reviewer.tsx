import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiFailure, completeSession, generateSuggestions, loadSession, selectSuggestion } from '../lib/api'
import { clearDraft, loadDraft, saveDraft } from '../lib/draft'
import { useFocusOnMount } from '../lib/a11y'
import type { FailureKind, Session, Suggestion } from '../lib/types'
import { ErrorState, LoadingState, UnavailableState } from './states'
import { GenerationNotice, SuggestionCard, SuggestionSkeletons } from './SuggestionList'
import { SelectedReviewEditor } from './SelectedReviewEditor'

type Phase =
  | { name: 'loading' }
  | { name: 'ready'; session: Session }
  | { name: 'gone' }
  | { name: 'error' }

export function Reviewer({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>({ name: 'loading' })
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [generating, setGenerating] = useState(false)
  const [genFailure, setGenFailure] = useState<FailureKind | null>(null)
  const [capReached, setCapReached] = useState(false)

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
  /* Never reset. The first batch is requested exactly once per mount, whatever
   * Strict Mode does to the effect around it. */
  const firstBatchRef = useRef(false)
  /* The redirect happens once. A second tap would double-count the completion
   * metric and race the navigation. The ref is the guard — it is readable
   * synchronously, before any re-render — and the state is only so the button
   * can show it. */
  const leavingRef = useRef(false)
  const [leaving, setLeaving] = useState(false)

  /* How many suggestions are on screen, readable synchronously. `generate` is
   * a useCallback keyed on the token, so the `suggestions` it closes over is
   * stale by the time an await resolves. Only the wording of an announcement
   * depends on this. Kept in step by hand at the two places suggestions are
   * set — never inside the state updater, which Strict Mode double-invokes. */
  const countRef = useRef(0)

  const generate = useCallback(async () => {
    if (generatingRef.current) return
    generatingRef.current = true

    setGenerating(true)
    setGenFailure(null)
    setAnnouncement('Writing suggestions…')

    try {
      const batch = await generateSuggestions(token)
      const isFirst = countRef.current === 0

      // Appended, never replaced. A customer who liked the second card and
      // pressed Generate More could otherwise never get it back, and at the
      // cap would be stuck with whichever batch happened to be last. New cards
      // land at the bottom, directly above the button that was just tapped —
      // prepending would put them off-screen and read as nothing happening.
      setSuggestions((current) => [...current, ...batch.suggestions])

      const added = batch.suggestions.length
      countRef.current += added
      const plural = added === 1 ? '' : 's'
      setAnnouncement(
        isFirst
          ? `${added} suggestion${plural} ready.`
          : `${added} more suggestion${plural} added below.`,
      )
    } catch (error) {
      const kind = error instanceof ApiFailure ? error.kind : 'server'

      // A dead token is terminal wherever it surfaces; everything else leaves
      // the screen exactly as it was and reports inline.
      if (kind === 'session-gone') {
        setPhase({ name: 'gone' })
      } else {
        if (kind === 'rate-limited') setCapReached(true)
        setGenFailure(kind)
        setAnnouncement("We couldn't generate new suggestions right now.")
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
        countRef.current = session.suggestions.length

        // Restored before anything is generated: a customer returning from
        // Google already has a review, and spending a cap slot to regenerate
        // suggestions they will never see is pure waste.
        const draft = loadDraft(token)
        if (draft && draft.selectedId !== null) {
          setSelectedId(draft.selectedId)
          setOriginalText(draft.originalText)
          setReviewText(draft.reviewText)
          setEditing(true)
          return
        }

        // GET never generates (R4), so an empty list is the normal first load
        // rather than a failure.
        if (session.suggestions.length === 0 && !firstBatchRef.current) {
          firstBatchRef.current = true
          void generate()
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
  }, [token, generate])

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
    setAnnouncement('Opening Google.')

    window.location.href = phase.session.googleReviewUrl
  }

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

      <Stage
        phase={phase}
        editing={editing}
        reviewText={reviewText}
        originalText={originalText}
        leaving={leaving}
        suggestions={suggestions}
        generating={generating}
        genFailure={genFailure}
        capReached={capReached}
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
          <div className="brand">Goopter</div>
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

  return (
    <>
      <div className="stack">
        <div className="brand">Goopter</div>
        <h1 className="merchant">{merchantName}</h1>
        {category !== null && <div className="category">{category}</div>}
      </div>

      <hr className="divider" />

      <div className="stack">
        <h2 className="question" tabIndex={-1} ref={heading}>
          How was your experience?
        </h2>
        <p className="lead">Here are a few ideas to help you write your review.</p>
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
          {generating ? 'Generating…' : 'Generate more suggestions'}
        </button>
      )}

      <div className="own">
        <span className="own__hint">Prefer to write your own?</span>
        <button className="link" onClick={onSkip}>
          Continue to Google →
        </button>
      </div>

      <p className="authenticity">
        Only use wording that reflects your genuine experience. You can edit any
        suggestion before posting.
      </p>
    </>
  )
}
