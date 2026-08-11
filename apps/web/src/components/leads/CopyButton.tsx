import { useEffect, useState } from 'react'

import { useMessages } from '../../lib/i18n/context'
import { copy } from '../../lib/leadsApi'

/** Copies, then says so for a moment.
 *
 *  The URL is always rendered beside this button, so a clipboard that refuses
 *  — an insecure origin, an in-app WebView — costs a manual selection rather
 *  than the link itself. That is why a failure is stated rather than hidden.
 *
 *  `label` falls back to the catalogue's own word for Copy in the body rather
 *  than as a default parameter, which cannot read a hook.
 */
export function CopyButton({ url, label }: { url: string; label?: string }) {
  const t = useMessages().leads.copy

  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  // Bumped on every click, so the countdown restarts even when the outcome is
  // the same value React would bail out on. Without it a second copy inherits
  // the first click's remaining time and the label reverts almost at once,
  // which reads as a copy that did not happen.
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (state === 'idle') return
    const timer = window.setTimeout(() => setState('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [state, attempt])

  return (
    <>
      <button
        type="button"
        className="lead-btn lead-btn--quiet"
        onClick={async () => {
          const copied = await copy(url)
          setAttempt((current) => current + 1)
          setState(copied ? 'copied' : 'failed')
        }}
      >
        {state === 'idle' ? (label ?? t.copy) : state === 'copied' ? t.copied : t.failed}
      </button>
      {/* The label changes on the control the operator just pressed, which a
          screen reader does not re-announce. The outcome is stated here. */}
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'copied'
          ? t.copiedAnnouncement
          : state === 'failed'
            ? t.failedAnnouncement
            : ''}
      </span>
    </>
  )
}
