import { useEffect, useLayoutEffect } from 'react'
import { NavigationType, useLocation, useNavigationType } from 'react-router-dom'

// Keyed by history entry, not pathname: `SetDetailPage`'s prev/next pager replaces the URL for
// every set it shows, so a per-pathname key would conflate scroll positions across looking at
// set A vs set B under the same route pattern.
const positions = new Map<string, number>()

/**
 * Resets scroll to the top on every forward navigation (push, and replace too — the pager's
 * paging is a replace, and each set it lands on is different content that should also start at
 * the top), but restores it on a browser-back pop. Same spirit as the persisted filter state
 * already documented in AGENTS.md: losing your place in a list every time you back out of a set
 * is exactly the "insupportable à l'usage" case that rule exists to avoid.
 *
 * `<BrowserRouter>` in its classic (non-data-router) mode has no built-in equivalent of
 * `<ScrollRestoration>`, and the app has one shared scrolling document rather than a per-screen
 * scroll container, so there is nothing else already doing this.
 */
export function useScrollRestoration() {
  const location = useLocation()
  const navigationType = useNavigationType()

  useEffect(() => {
    // Tracked continuously while this entry is the active one, not saved once on the way out —
    // by the time a route change's own cleanup would run, the new page has already committed and
    // `window.scrollY` no longer reflects the page being left.
    const save = () => positions.set(location.key, window.scrollY)
    window.addEventListener('scroll', save, { passive: true })
    return () => window.removeEventListener('scroll', save)
  }, [location.key])

  useLayoutEffect(() => {
    window.scrollTo(0, navigationType === NavigationType.Pop ? (positions.get(location.key) ?? 0) : 0)
  }, [location.key, navigationType])
}
