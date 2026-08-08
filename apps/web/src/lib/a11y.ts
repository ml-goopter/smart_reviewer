import { useEffect, useRef } from 'react'

/** Moves focus to a heading when a stage appears.
 *
 *  Every stage change here replaces the whole screen without navigating, so a
 *  screen reader is given no reason to start reading and a keyboard user is
 *  left with focus on a button that no longer exists. Focusing the new heading
 *  is what makes the transition perceivable.
 *
 *  The element needs `tabIndex={-1}` to be focusable without joining the tab
 *  order.
 */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null)

  useEffect(() => {
    // preventScroll: the heading is already at the top of a fresh screen, and
    // letting the browser scroll to it fights the layout on short viewports.
    ref.current?.focus({ preventScroll: true })
  }, [])

  return ref
}
