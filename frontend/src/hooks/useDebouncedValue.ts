import { useEffect, useState } from 'react'

/**
 * Holds back a fast-changing value so a server-side query keyed on it doesn't fire on every
 * keystroke. `delayMs` resets on every change — only a pause of that length commits a value.
 */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
