import { useEffect, useState } from 'react'

import { useLocale, useMessages } from '../../lib/i18n/context'
import {
  DEFAULT_TERM_DAYS,
  LeadFailure,
  fetchContext,
  putContext,
  setSubscriptionStatus,
  subscribe,
} from '../../lib/leadsApi'
import type { MerchantContext, ReviewContext, Subscription } from '../../lib/leadTypes'
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

/** `lastValidDay` is a plain `YYYY-MM-DD` already resolved in the operator's
 *  timezone. Parsed as UTC noon rather than handed to `new Date()` directly: a
 *  bare date string parses as UTC midnight, which in any negative-offset zone
 *  renders as the day before — the exact off-by-one the field exists to stop. */
function lastDay(isoDate: string, locale: string): string {
  const [y = 0, m = 1, d = 1] = isoDate.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
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
  const sub = leads.subscription
  // A date under a Chinese header should not be formatted for whatever the
  // machine happens to be set to.
  const { locale } = useLocale()

  const [loaded, setLoaded] = useState<MerchantContext | null>(null)
  const [form, setForm] = useState<FormText>(EMPTY)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle')
  /* Which failure, not its wording. A rendered sentence would still be sitting
   * there in the old language after the drawer changes it — and the effect
   * below must not depend on the catalogue, or every language change would
   * refetch the merchant. */
  const [error, setError] = useState<'load' | 'save' | 'link' | null>(null)
  /* Subscription writes are tracked apart from the context form: they are a
   * different request against a different endpoint, and a failed renewal must
   * not read as a failed save of the text the operator just typed. */
  const [subBusy, setSubBusy] = useState(false)
  const [subError, setSubError] = useState(false)

  useEffect(() => {
    fetchContext(merchantId)
      .then((body) => {
        setLoaded(body)
        setForm(textFrom(body.context))
      })
      .catch(() => setError('load'))
  }, [merchantId])

  /** Any edit un-says "Saved". Leaving the confirmation up over changed text
   *  makes an unsaved edit look committed. */
  function edit(field: keyof FormText, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
    setStatus((current) => (current === 'saved' ? 'idle' : current))
  }

  /* Patches the loaded merchant from the response rather than refetching: the
   * operator may have unsaved context text in the form below, and a refetch
   * would reset it under them. */
  function writeSubscription(call: () => Promise<Subscription>) {
    if (subBusy) return
    setSubBusy(true)
    setSubError(false)
    call()
      .then((subscription) => {
        setLoaded((current) =>
          current === null
            ? current
            : { ...current, merchant: { ...current.merchant, subscription } },
        )
      })
      .catch(() => setSubError(true))
      .finally(() => setSubBusy(false))
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
          ? 'link'
          : 'save',
      )
    }
  }

  const wording =
    error === null
      ? null
      : error === 'load'
        ? t.loadFailed
        : error === 'link'
          ? t.linkRejected
          : t.saveFailed

  // `.leads` is the page frame — max width, gutters, type. The editor is its
  // own route, so it has to carry the frame itself; without it the form runs
  // edge to edge on a wide window.
  if (error !== null && loaded === null) {
    return (
      <div className="leads">
        <TopBar />
        <p className="lead-error" role="alert">
          {wording}
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
          {loaded.merchant.slug} ·{' '}
          {loaded.merchant.subscription == null
            ? sub.notSubscribed
            : loaded.merchant.subscription.status}
          {loaded.merchant.googleRating !== null && (
            <>
              {' · '}
              {loaded.merchant.googleRating} ★ · {loaded.merchant.googleReviewCount}{' '}
              {t.reviews}
              {loaded.merchant.googleSyncedAt !== null && (
                <>
                  {' '}
                  {t.asOf(
                    new Date(loaded.merchant.googleSyncedAt).toLocaleDateString(locale),
                  )}
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

      {/* The subscription is what decides whether the URL above opens, so it
          sits directly under it. Not in the form below: that one replaces eight
          context fields on submit, and a term is not a draft to be saved. */}
      <div className="lead-card">
        <h3 className="lead-heading">{sub.heading}</h3>

        <p className="lead-sub">
          {loaded.merchant.subscription == null ? (
            sub.notSubscribed
          ) : (
            <>
              {loaded.merchant.subscription.status} · {sub.expires}{' '}
              {lastDay(loaded.merchant.subscription.lastValidDay, locale)}
            </>
          )}
        </p>

        <div className="lead-actions">
          <button
            type="button"
            className="lead-btn lead-btn--quiet"
            disabled={subBusy}
            onClick={() => writeSubscription(() => subscribe(merchantId))}
          >
            {loaded.merchant.subscription == null
              ? sub.subscribe(DEFAULT_TERM_DAYS)
              : sub.renew(DEFAULT_TERM_DAYS)}
          </button>

          {loaded.merchant.subscription != null &&
            (loaded.merchant.subscription.status === 'ACTIVE' ? (
              <button
                type="button"
                className="lead-btn lead-btn--quiet"
                disabled={subBusy}
                onClick={() =>
                  writeSubscription(() =>
                    setSubscriptionStatus(merchantId, 'CANCELLED'),
                  )
                }
              >
                {sub.suspend}
              </button>
            ) : (
              <button
                type="button"
                className="lead-btn lead-btn--quiet"
                disabled={subBusy}
                onClick={() =>
                  writeSubscription(() => setSubscriptionStatus(merchantId, 'ACTIVE'))
                }
              >
                {sub.resume}
              </button>
            ))}
        </div>

        <p className="lead-note">
          {loaded.merchant.subscription != null &&
          loaded.merchant.subscription.status !== 'ACTIVE'
            ? sub.suspendedNote
            : sub.renewNote}
        </p>

        {subError && (
          <p className="lead-error" role="alert">
            {sub.failed}
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
          {wording !== null && <p className="lead-error">{wording}</p>}
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
