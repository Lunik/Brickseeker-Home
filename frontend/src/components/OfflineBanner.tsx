import { useBackendReachable } from '../lib/backend-reachability'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

/**
 * A passive "Hors-ligne" capsule, mirroring iOS's `OfflineIndicatorView` — pinned above
 * everything (including the full-bleed scanner, exactly where a user is most likely to walk out
 * of LAN range) and never blocking a tap underneath it.
 */
export default function OfflineBanner() {
  const online = useOnlineStatus()
  const backendReachable = useBackendReachable()
  if (online && backendReachable) return null

  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center pt-[max(0.5rem,env(safe-area-inset-top))]"
      aria-live="polite"
    >
      <span className="rounded-full bg-black/80 px-3 py-1 text-xs font-medium text-white shadow-lg backdrop-blur">
        Hors-ligne
      </span>
    </div>
  )
}
