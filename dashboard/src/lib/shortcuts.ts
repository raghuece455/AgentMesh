import { useEffect, useRef } from 'react'

/** True when a key press belongs to the user typing or to an open dialog, not to a page shortcut. */
export function isTypingTarget(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null
  if (!target)
    return false
  if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    return true
  return Boolean(document.querySelector('[role="dialog"], [role="menu"]'))
}

/**
 * Single-key page shortcuts (`j`, `[`, `Escape`, ...). Ignored while typing, while a dialog or
 * menu is open, and when a modifier key is held, so browser and palette shortcuts keep working.
 */
export function useShortcuts(bindings: Record<string, () => void>, enabled = true) {
  const latest = useRef(bindings)
  latest.current = bindings
  useEffect(() => {
    if (!enabled)
      return
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented || isTypingTarget(event))
        return
      const action = latest.current[event.key]
      if (action) {
        event.preventDefault()
        action()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])
}
