import { useSyncExternalStore } from 'react'

function subscribe(onStoreChange: () => void): () => void {
  window.addEventListener('online', onStoreChange)
  window.addEventListener('offline', onStoreChange)
  return () => {
    window.removeEventListener('online', onStoreChange)
    window.removeEventListener('offline', onStoreChange)
  }
}

function snapshot(): boolean {
  return navigator.onLine
}

/**
 * Device-wide network reachability — Wi-Fi/cellular connectivity, not "can we reach the backend
 * specifically" (this app is self-hosted on a home LAN, and a phone can be online while that LAN
 * is unreachable — see `lib/backend-reachability.ts` for that narrower signal). Mirrors iOS's
 * `NetworkMonitor.isConnected`.
 */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => true)
}
