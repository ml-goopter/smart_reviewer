import { useEffect, useRef, useState } from 'react'

import { useMessages } from '../../lib/i18n/context'
import { LeadFailure, fetchContext, putContext } from '../../lib/leadsApi'
import type { MerchantContext, ReviewContext } from '../../lib/leadTypes'
import { TopBar } from '../TopBar'
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
 * column read as a form to get through rather than a description to write.
 *
 * Only the grouping lives here now. Every word the operator reads comes from
 * the catalogue, keyed by the same field names the form itself uses. */
const SECTIONS = [
  { key: 'offers', fields: ['products', 'services', 'menuItems'] },
  { key: 'voice', fields: ['sellingPoints', 'approvedKeywords', 'experienceTopics'] },
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
  /** Absent for the fields whose label says it all. Nothing is rendered then,
   *  and `aria-describedby` is left off rather than pointing at an empty
   *  element — a dangling reference is announced as nothing at all. */
  hint?: string
  children: (id: string, describedBy: string | undefined) => React.ReactNode
}) {
  const id = `lead-${name}`
  const describedBy = hint === undefined ? undefined : `${id}-hint`

  return (
    <div className="lead-field">
      <label htmlFor={id}>{label}</label>
      {describedBy !== undefined && (
        <span className="lead-hint" id={describedBy}>
          {hint}
        </span>
      )}
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
  const leads = useMessages().leads
  const t = leads.editor

  const [loaded, setLoaded] = useState<MerchantContext | null>(null)
  const [form, setForm] = useState<FormText>(EMPTY)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [error, setError] = useState<string | null>(null)

  /* The catalogue, readable inside an effect and a handler without either
   * depending on it. Both set an error message, and the language on screen at
   * the moment it is set is the one to word it in — but adding `t` to the
   * effect below would refetch the merchant on every language change. */
  const wording = useRef(t)
  wording.current = t

  useEffect(() => {
    fetchContext(merchantId)
      .then((body) => {
        setLoaded(body)
        setForm(textFrom(body.context))
      })
      .catch(() => setError(wording.current.loadFailed))
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
          ? wording.current.linkRejected
          : wording.current.saveFailed,
      )
    }
  }

  // `.leads` is the page frame — max width, gutters, type. The editor is its
  // own route, so it has to carry the frame itself; without it the form runs
  // edge to edge on a wide window.
  if (error !== null && loaded === null) {
    return (
      <div className="leads">
        <TopBar />
        <p className="lead-error" role="alert">
          {error}
        </p>
      </div>
    )
  }
  if (loaded === null) {
    return (
      <div className="leads">
        <TopBar />
        <p className="lead-empty">{leads.loading}</p>
      </div>
    )
  }

  return (
    <div className="leads lead-panel">
      {/* Its own route, so it carries the bar itself — the crawler shell that
        * mounts one is not above this. */}
      <TopBar />
      <button
        type="button"
        className="lead-btn lead-btn--quiet lead-back"
        onClick={onBack}
      >
        {t.back}
      </button>

      <div className="lead-card">
        <h2 className="lead-heading">{loaded.merchant.name}</h2>
        <p className="lead-sub">
          {loaded.merchant.slug} · {loaded.merchant.status}
          {loaded.merchant.googleRating !== null && (
            <>
              {' · '}
              {loaded.merchant.googleRating} ★ · {loaded.merchant.googleReviewCount}{' '}
              {t.reviews}
              {loaded.merchant.googleSyncedAt !== null && (
                <>
                  {' '}
                  {t.asOf(new Date(loaded.merchant.googleSyncedAt).toLocaleDateString())}
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

      <p className="lead-note">{t.note}</p>

      <form className="lead-editor" onSubmit={submit}>
        <section className="lead-section">
          <h3>{t.about}</h3>

          <Field
            name="businessSummary"
            label={t.fields.businessSummary.label}
            hint={t.fields.businessSummary.hint}
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
          <section className="lead-section" key={section.key}>
            <h3>{t[section.key].title}</h3>
            <p className="lead-caption">{t[section.key].caption}</p>

            <div className="lead-grid">
              {section.fields.map((key) => {
                const field = t.fields[key]
                return (
                  <Field
                    key={key}
                    name={key}
                    label={field.label}
                    {...('hint' in field ? { hint: field.hint } : {})}
                  >
                    {(id, describedBy) => (
                      <textarea
                        id={id}
                        aria-describedby={describedBy}
                        // Six: Google supplies up to eight attributes, and the
                        // prefilled selling points should not open scrolled.
                        rows={6}
                        placeholder={t.onePerLine}
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
          <h3>{t.instruction.title}</h3>

          <Field
            name="customInstructions"
            label={t.fields.customInstructions.label}
            hint={t.fields.customInstructions.hint}
          >
            {(id, describedBy) => (
              <textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                placeholder={t.noLinks}
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
            {status === 'saving' ? t.saving : status === 'saved' ? t.saved : t.save}
          </button>
          <span className="lead-sub" role="status" aria-live="polite">
            {status === 'saved' ? t.confirmation : ''}
          </span>
        </div>
      </form>
    </div>
  )
}
