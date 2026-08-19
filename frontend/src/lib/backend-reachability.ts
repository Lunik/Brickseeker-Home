/**
 * Whether *this app's own backend* has answered recently — narrower than `useOnlineStatus`, and
 * the signal that actually matters here: a phone on Wi-Fi can report `navigator.onLine === true`
 * while the home LAN server specifically is down, asleep, or the phone is on the wrong subnet.
 *
 * Fed from one choke point: `api/client.ts` calls `reportRequestOutcome` after every request
 * settles, so every existing call site in the app gets this signal for free. While unreachable, a
 * backoff probe against `GET /api/health` keeps checking on its own, so recovery is detected even
 * on a screen that fires no requests of its own (a persisted list showing cached data has nothing
 * left to retry once its own background refetch has already failed once).
 */

import { useSyncExternalStore } from 'react'

const PROBE_INTERVAL_MS = 15_000

const listeners = new Set<() => void>()
let reachable = true
let probeTimer: ReturnType<typeof setTimeout> | null = null

function notify(): void {
  for (const listener of listeners) listener()
}

function scheduleProbe(): void {
  if (probeTimer !== null) return
  probeTimer = setTimeout(() => {
    probeTimer = null
    void probeNow()
  }, PROBE_INTERVAL_MS)
}

function setReachable(next: boolean): void {
  if (next !== reachable) {
    reachable = next
    notify()
  }
  if (!next) scheduleProbe()
}

/**
 * Called by `api/client.ts` after every request settles. `ok` is true for *any* HTTP response —
 * even a 4xx/5xx, since that proves the backend answered — and false only for a genuine network
 * failure (a plain `TypeError` from `fetch`, not an `ApiError` built from a real response).
 */
export function reportRequestOutcome(ok: boolean): void {
  setReachable(ok)
}

/** Actively re-checks right now, rather than waiting for the next request or backoff tick — used
 *  by the offline-scan sync engine on `online`/foreground so it doesn't sit on a stale reading. */
export async function probeNow(): Promise<boolean> {
  try {
    const response = await fetch('/api/health', { credentials: 'same-origin' })
    setReachable(true)
    return response.ok
  } catch {
    setReachable(false)
    return false
  }
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange)
  return () => {
    listeners.delete(onStoreChange)
  }
}

function snapshot(): boolean {
  return reachable
}

export function useBackendReachable(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => true)
}

/** The non-React form of `snapshot`/`subscribe`, for the offline-scan sync engine — it needs to
 *  react to reachability flipping true without being a component. */
export const isBackendReachable = snapshot
export const subscribeReachability = subscribe
