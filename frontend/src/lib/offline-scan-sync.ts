/**
 * Auto-syncs scans queued while the backend was unreachable, replaying each through the same
 * `POST /scan/lookup` path a live camera/manual scan uses — a real `ScanEvent` gets created, with
 * the original `scannedAt` so History shows when the scan actually happened, not when it synced.
 *
 * Triggered by the `online` event, the tab becoming visible again, and whenever
 * `backend-reachability` itself flips to reachable — the last one is the real trigger in the
 * common case here, since `navigator.onLine` can stay `true` while the LAN server specifically is
 * down; the other two just prompt an immediate reachability probe rather than trusting a possibly
 * stale reading.
 */

import { api, ApiError } from '../api/client'
import type { ResolveResult } from '../api/types'
import { isBackendReachable, probeNow, subscribeReachability } from './backend-reachability'
import { offlineScanQueue, ready as offlineScanQueueReady, type PendingScan } from './offline-scan-queue'
import { queryClient } from './query-client'

let syncing = false

/** Returns `true` once this item is no longer pending (synced or moved to `failed`), `false` on a
 *  genuine network failure — the signal to stop this pass rather than burn through the rest of the
 *  queue against a backend that just went away again mid-sync. */
async function syncOne(item: PendingScan): Promise<boolean> {
  try {
    const result = await api.post<ResolveResult>('/scan/lookup', {
      setNum: item.setNum,
      source: item.source,
      priceSeenEur: item.priceSeenEur,
      latitude: item.latitude,
      longitude: item.longitude,
      scannedAt: item.scannedAt,
    })
    if (result.set) {
      await offlineScanQueue.remove(item.id)
      return true
    }
    // The offline catalogue snapshot disagreed with live data, or the number was never valid —
    // not a connectivity problem, so don't let it block every item queued after it.
    await offlineScanQueue.markFailed(
      item.id,
      result.status === 'ambiguous'
        ? 'Plusieurs sets correspondent — à résoudre manuellement.'
        : 'Set introuvable.',
    )
    return true
  } catch (caught) {
    if (caught instanceof ApiError) {
      // A real response came back — not a connectivity problem, so retrying on the next trigger
      // can't fix it either (a missing Rebrickable API key, an expired session…). Surface it and
      // move on to the next item, rather than leaving it stuck "pending" forever with no visible
      // explanation while genuinely being reachable.
      await offlineScanQueue.markFailed(item.id, caught.message)
      return true
    }
    // A thrown non-`ApiError` is a genuine network failure — leave this item pending and stop the
    // pass; a backend that just dropped mid-sync will fail every subsequent item the same way.
    return false
  }
}

export async function syncPendingScans(): Promise<void> {
  if (syncing) return
  syncing = true
  try {
    await offlineScanQueueReady
    const reachable = await probeNow()
    if (!reachable) return

    // Snapshot at the start: an item queued mid-pass (a fresh offline scan while this sync is
    // still running) is picked up by the next trigger, not stitched into this one.
    const items = offlineScanQueue.all().filter((item) => item.status === 'pending')
    if (items.length === 0) return

    for (const item of items) {
      const handled = await syncOne(item)
      if (!handled) break
    }
    await queryClient.invalidateQueries({ queryKey: ['history'] })
  } finally {
    syncing = false
  }
}

let initialized = false

/** Registers the sync triggers once. Idempotent, so it's safe to call from `main.tsx` without a
 *  guard at the call site. */
export function initOfflineScanSync(): void {
  if (initialized) return
  initialized = true

  window.addEventListener('online', () => void syncPendingScans())
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void syncPendingScans()
  })
  subscribeReachability(() => {
    if (isBackendReachable()) void syncPendingScans()
  })

  void syncPendingScans()
}
