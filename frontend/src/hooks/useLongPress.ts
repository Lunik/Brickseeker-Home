import { useCallback, useRef } from 'react'

/** iOS's own `.contextMenu` gesture threshold — matched so this reads as the same gesture. */
const PRESS_MS = 500
/** Beyond this, a moving finger is a scroll, not a hold; iOS Safari's own scroll-vs-tap slop. */
const MOVE_TOLERANCE_PX = 10

/**
 * Long-press-to-open-quick-actions, the touch counterpart of the desktop right-click already
 * wired to `onContextMenu` everywhere a row has bulk actions. The iOS app gets this for free from
 * SwiftUI's `.contextMenu`, which is itself long-press on a touch device — there is no such
 * built-in on the web, so it has to be hand-rolled from Pointer Events.
 *
 * Returns `onContextMenu` unchanged (desktop) plus the touch pointer handlers, and a
 * `consumeIfFired()` for the row's own `onClick` to call first — a `click` still follows the
 * `touchend` that ends a long press, and whether the browser actually suppresses it after
 * `pointerup`'s `preventDefault()` is exactly the kind of cross-browser detail not worth trusting;
 * checking explicitly at the one place that matters is simpler than chasing that reliably.
 *
 * `enabled` (default `true`) gates the gesture entirely rather than leaving the caller to decide
 * whether to attach the returned handlers — a row with nothing to trigger (no bulk actions, or
 * selection mode already claiming the tap) must never start the timer at all, or a held-a-touch-
 * too-long tap would silently eat the next click for no visible effect.
 */
export function useLongPress<T>(item: T, onTrigger: (item: T) => void, enabled = true) {
  const timerRef = useRef<number | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const fired = useRef(false)

  const clear = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    timerRef.current = null
    start.current = null
  }, [])

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (!enabled) return
      if (event.pointerType !== 'touch' && event.pointerType !== 'pen') return
      start.current = { x: event.clientX, y: event.clientY }
      timerRef.current = window.setTimeout(() => {
        fired.current = true
        onTrigger(item)
      }, PRESS_MS)
    },
    [enabled, item, onTrigger],
  )

  const onPointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (!start.current) return
      const dx = event.clientX - start.current.x
      const dy = event.clientY - start.current.y
      if (Math.hypot(dx, dy) > MOVE_TOLERANCE_PX) clear()
    },
    [clear],
  )

  const onContextMenu = useCallback(
    (event: React.MouseEvent) => {
      if (!enabled) return
      event.preventDefault()
      onTrigger(item)
    },
    [enabled, item, onTrigger],
  )

  return {
    onPointerDown,
    onPointerMove,
    onPointerUp: clear,
    onPointerCancel: clear,
    onContextMenu,
    /** Call at the top of the row's own `onClick`; a `true` return means "swallow this click". */
    consumeIfFired: () => {
      if (!fired.current) return false
      fired.current = false
      return true
    },
  }
}
