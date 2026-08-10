import { useEffect, useState } from 'react'

import { LeadFailure, fetchContext, putContext } from '../../lib/leadsApi'
import type { MerchantContext, ReviewContext } from '../../lib/leadTypes'
import { CopyButton } from './CopyButton'

/** What the eight textareas hold: raw text, exactly as typed.
 *
 *  Never normalise on change. A trimmed value fed back into a controlled
 *  textarea makes a space untypable, and dropping empty lines makes Enter
 *  unpressable — so "one per line" becomes one word per field. Normalisation
 *  belongs on submit, where it is applied once to a finished value.
 */
type FormText = Record<keyof ReviewContext, string>

const EMPTY: FormText = {
  businessSummary: '',
  products: '',
  services: '',
  menuItems: '',
  sellingPoints: '',
  approvedKeywords: '',
  experienceTopics: '',
  customInstructions: '',
}

/* Grouped by the question each field answers, because eight textareas in one
 * column read as a form to get through rather than a description to write. */
const SECTIONS = [
  {
    title: 'What it offers',
    caption: 'None of this is in Google. It is what makes a review sound like a real visit.',
    fields: ['products', 'services', 'menuItems'],
  },
  {
    title: 'How reviews should read',
    caption: 'The angles a suggestion is written from, and the words it may use.',
    fields: ['sellingPoints', 'approvedKeywords', 'experienceTopics'],
  },
] as const

/* Every field here is fed to the model, so each hint says two things: what
 * belongs in it, and whether Google prefilled it. The three Google cannot
 * answer are the reason this screen exists. */
const LISTS = [
  [
    'products',
    'Products',
    'What customers buy, in their words — “beef pho”, “Vietnamese coffee”. Google has no field for this.',
  ],
  [
    'services',
    'Services',
    'What you do rather than sell — “catering”, “walk-ins welcome”. Google has no field for this.',
  ],
  [
    'menuItems',
    'Menu items',
    'Named dishes a reviewer might single out. Google has no field for this.',
  ],
  [
    'sellingPoints',
    'Selling points',
    'What regulars actually praise. Prefilled from Google’s attributes (dine-in, takeout) — those are true of everyone, so replace them with what makes this place different.',
  ],
  [
    'approvedKeywords',
    'Approved keywords',
    'Words the merchant is happy to see in a review. Offered to the model, never forced into it.',
  ],
  [
    'experienceTopics',
    'Experience topics',
    'One angle per suggestion, rotating each batch, so three cards read as different reviews. Prefilled from the business category.',
  ],
] as const

/** One entry per line, both ways. A comma-separated box would make "fish, chips
 *  and mushy peas" two products and a fragment. */
const linesOf = (values: string[] | null) => (values ?? []).join('\n')
const toList = (text: string) => {
  const items = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
  return items.length === 0 ? null : items
}
const toText = (value: string) => (value.trim() === '' ? null : value.trim())

const textFrom = (context: ReviewContext): FormText => ({
  businessSummary: context.businessSummary ?? '',
  products: linesOf(context.products),
  services: linesOf(context.services),
  menuItems: linesOf(context.menuItems),
  sellingPoints: linesOf(context.sellingPoints),
  approvedKeywords: linesOf(context.approvedKeywords),
  experienceTopics: linesOf(context.experienceTopics),
  customInstructions: context.customInstructions ?? '',
})

const contextFrom = (text: FormText): ReviewContext => ({
  businessSummary: toText(text.businessSummary),
  products: toList(text.products),
  services: toList(text.services),
  menuItems: toList(text.menuItems),
  sellingPoints: toList(text.sellingPoints),
  approvedKeywords: toList(text.approvedKeywords),
  experienceTopics: toList(text.experienceTopics),
  customInstructions: toText(text.customInstructions),
})

/** Label, hint and control.
 *
 *  An explicit `htmlFor`/`id` pair rather than a wrapping label, and the hint
 *  attached with `aria-describedby`: wrapped inside the label, the hint would
 *  become part of the field's accessible name, so a screen reader would
 *  announce the whole paragraph every time focus landed on the box.
 */
function Field({
  name,
  label,
  hint,
  children,
}: {
  name: string
  label: string
  hint: string
  children: (id: string, describedBy: string) => React.ReactNode
}) {
  const id = `lead-${name}`
  const describedBy = `${id}-hint`

  return (
    <div className="lead-field">
      <label htmlFor={id}>{label}</label>
      <span className="lead-hint" id={describedBy}>
        {hint}
      </span>
      {children(id, describedBy)}
    </div>
  )
}

export function ContextEditor({
  merchantId,
  onBack,
}: {
  merchantId: string
  onBack: () => void
}) {
  const [loaded, setLoaded] = useState<MerchantContext | null>(null)
  const [form, setForm] = useState<FormText>(EMPTY)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchContext(merchantId)
      .then((body) => {
        setLoaded(body)
        setForm(textFrom(body.context))
      })
      .catch(() => setError('Could not load this merchant.'))
  }, [merchantId])

  /** Any edit un-says "Saved". Leaving the confirmation up over changed text
   *  makes an unsaved edit look committed. */
  function edit(field: keyof FormText, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
    setStatus((current) => (current === 'saved' ? 'idle' : current))
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setStatus('saving')
    setError(null)
    try {
      setForm(textFrom(await putContext(merchantId, contextFrom(form))))
      setStatus('saved')
    } catch (failure) {
      setStatus('idle')
      setError(
        failure instanceof LeadFailure && failure.code === 'instructions_contain_url'
          ? 'Custom instructions cannot contain a link or web address — generated reviews reject URLs, so every suggestion for this merchant would fail.'
          : 'Could not save.',
      )
    }
  }

  // `.leads` is the page frame — max width, gutters, type. The editor is its
  // own route, so it has to carry the frame itself; without it the form runs
  // edge to edge on a wide window.
  if (error !== null && loaded === null) {
    return (
      <div className="leads">
        <p className="lead-error" role="alert">
          {error}
        </p>
      </div>
    )
  }
  if (loaded === null) {
    return (
      <div className="leads">
        <p className="lead-empty">Loading…</p>
      </div>
    )
  }

  return (
    <div className="leads lead-panel">
      <button
        type="button"
        className="lead-btn lead-btn--quiet lead-back"
        onClick={onBack}
      >
        ← Back
      </button>

      <div className="lead-card">
        <h2 className="lead-heading">{loaded.merchant.name}</h2>
        <p className="lead-sub">
          {loaded.merchant.slug} · {loaded.merchant.status}
          {loaded.merchant.googleRating !== null && (
            <>
              {' · '}
              {loaded.merchant.googleRating} ★ · {loaded.merchant.googleReviewCount}{' '}
              reviews
              {loaded.merchant.googleSyncedAt !== null && (
                <>
                  {' '}
                  (as of {new Date(loaded.merchant.googleSyncedAt).toLocaleDateString()})
                </>
              )}
            </>
          )}
        </p>
        {loaded.merchant.url !== null && (
          <p className="lead-url">
            <code>{loaded.merchant.url}</code> <CopyButton url={loaded.merchant.url} />
          </p>
        )}
      </div>

      <p className="lead-note">
        Google supplies the summary and the attributes. Everything else here is
        what it cannot know — and together they are the whole of what the AI is
        told about this merchant.
      </p>

      <form className="lead-editor" onSubmit={submit}>
        <section className="lead-section">
          <h3>About the business</h3>

          <Field
            name="businessSummary"
            label="Business summary"
            hint="What the business is, in two or three specific sentences. Prefilled from Google’s editorial line, or a plain sentence built from the category and city when Google had none."
          >
            {(id, describedBy) => (
              <textarea
                id={id}
                aria-describedby={describedBy}
                rows={4}
                value={form.businessSummary}
                onChange={(event) => edit('businessSummary', event.target.value)}
              />
            )}
          </Field>
        </section>

        {SECTIONS.map((section) => (
          <section className="lead-section" key={section.title}>
            <h3>{section.title}</h3>
            <p className="lead-caption">{section.caption}</p>

            <div className="lead-grid">
              {section.fields.map((key) => {
                const [, label, hint] = LISTS.find(([name]) => name === key)!
                return (
                  <Field key={key} name={key} label={label} hint={hint}>
                    {(id, describedBy) => (
                      <textarea
                        id={id}
                        aria-describedby={describedBy}
                        // Six: Google supplies up to eight attributes, and the
                        // prefilled selling points should not open scrolled.
                        rows={6}
                        placeholder="One per line"
                        value={form[key]}
                        onChange={(event) => edit(key, event.target.value)}
                      />
                    )}
                  </Field>
                )
              })}
            </div>
          </section>
        ))}

        <section className="lead-section">
          <h3>House rules</h3>

          <Field
            name="customInstructions"
            label="Custom instructions"
            hint="House style, not facts — “keep it under three sentences”, “say clinic, not shop”. No links: generated text containing a URL fails validation, so one here would break every suggestion for this merchant."
          >
            {(id, describedBy) => (
              <textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                placeholder="No links or web addresses"
                value={form.customInstructions}
                onChange={(event) => edit('customInstructions', event.target.value)}
              />
            )}
          </Field>
        </section>

        {/* The live region is the container, not the message: a region that
            arrives in the same commit as its first text is usually not
            announced at all. */}
        <div role="status" aria-live="polite">
          {error !== null && <p className="lead-error">{error}</p>}
        </div>

        {/* Sticky: the form is now taller than a viewport, and a save button
            that scrolled away would make a long edit feel unsaveable. */}
        <div className="lead-actions-bar">
          <button type="submit" className="lead-btn" disabled={status === 'saving'}>
            {status === 'saving' ? 'Saving…' : status === 'saved' ? 'Saved' : 'Save context'}
          </button>
          <span className="lead-sub" role="status" aria-live="polite">
            {status === 'saved' ? 'All eight fields replaced.' : ''}
          </span>
        </div>
      </form>
    </div>
  )
}
