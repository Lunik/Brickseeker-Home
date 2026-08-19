/**
 * Durable queue for scans resolved while the backend was unreachable.
 *
 * Deliberately **not** merged into `lib/batch-session.ts`, even though the two interact at the UI
 * layer (see `pages/ScannerPage.tsx`). `batch-session.ts` is ephemeral by its own design — a UI
 * grouping for comparing a sweep of scans, gone the moment the tab closes. A pending offline scan
 * is different in kind: it's an *unrecorded `ScanEvent`*, user-generated data in the same category
 * `clear_cache()` already protects server-side (survives a cache clear same as `ScanEvent`/
 * `SetPurchaseRecord`/`PriceAlert`, since none of it is re-derivable from an API). Losing it
 * silently drops a real scan, its timestamp and its location — that has to survive a tab close,
 * which is exactly what `sessionStorage`-backed `batch-session.ts` does not do.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import { useSyncExternalStore } from 'react'

import type { LegoSet } from '../api/types'

export interface PendingScan {
  id: number
  setNum: string
  /** camera | manualEntry — mirrors `LookupIn.source`, threaded through on sync. */
  source: string
  /** ISO timestamp of the moment the scan actually happened, not when it syncs. */
  scannedAt: string
  priceSeenEur: number | null
  latitude: number | null
  longitude: number | null
  /** The offline-catalogue snapshot at scan time, for immediate display before sync. */
  resolvedSet: LegoSet
  status: 'pending' | 'failed'
  error: string | null
}

type PendingScanInput = Omit<PendingScan, 'id' | 'status' | 'error'>

interface OfflineScanQueueSchema extends DBSchema {
  pendingScans: { key: number; value: PendingScan }
}

const DB_NAME = 'brickseeker-offline-scans'
const DB_VERSION = 1

let dbPromise: Promise<IDBPDatabase<OfflineScanQueueSchema>> | null = null

function db(): Promise<IDBPDatabase<OfflineScanQueueSchema>> {
  dbPromise ??= openDB<OfflineScanQueueSchema>(DB_NAME, DB_VERSION, {
    upgrade(database) {
      database.createObjectStore('pendingScans', { keyPath: 'id', autoIncrement: true })
    },
  })
  return dbPromise
}

const listeners = new Set<() => void>()
/** Mirrors the IndexedDB contents so `useSyncExternalStore` has a synchronous snapshot to read —
 *  IndexedDB itself is only ever async. Loaded once at module init, kept current by `refresh()`
 *  after every mutation. */
let cache: PendingScan[] = []

function notify(): void {
  for (const listener of listeners) listener()
}

async function refresh(): Promise<void> {
  try {
    cache = await (await db()).getAll('pendingScans')
  } catch {
    // Private browsing, a blocked/exhausted store, or a failed upgrade. Queueing a scan will
    // surface its own error to the user; a *read* failing must not take the app down with an
    // unhandled rejection, so the queue simply reads as empty.
    cache = []
  }
  notify()
}

/**
 * Resolves once the initial IndexedDB read has populated `cache`. The sync engine's very first
 * pass on page load races this module's own async init against `main.tsx` calling
 * `initOfflineScanSync()` — without awaiting this first, that first pass could read `cache` while
 * it's still `[]`, silently skip a queue that genuinely has items, and never be re-triggered
 * (nothing else changes afterward to prompt a second attempt).
 *
 * Never rejects: `refresh` swallows storage failures, so awaiting this is always safe.
 */
export const ready: Promise<void> = refresh()

async function enqueue(input: PendingScanInput): Promise<number> {
  const database = await db()
  const id = await database.add('pendingScans', { ...input, status: 'pending', error: null } as PendingScan)
  await refresh()
  return id
}

async function remove(id: number): Promise<void> {
  await (await db()).delete('pendingScans', id)
  await refresh()
}

async function markFailed(id: number, error: string): Promise<void> {
  const database = await db()
  const existing = await database.get('pendingScans', id)
  if (!existing) return
  await database.put('pendingScans', { ...existing, status: 'failed', error })
  await refresh()
}

async function markPending(id: number): Promise<void> {
  const database = await db()
  const existing = await database.get('pendingScans', id)
  if (!existing) return
  await database.put('pendingScans', { ...existing, status: 'pending', error: null })
  await refresh()
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange)
  return () => {
    listeners.delete(onStoreChange)
  }
}

function snapshot(): PendingScan[] {
  return cache
}

/** A stable identity: `useSyncExternalStore` compares snapshots by reference, so returning a fresh
 *  `[]` on each call would loop forever the moment anything renders this without a live store. */
const EMPTY: PendingScan[] = []

export function usePendingScans(): PendingScan[] {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY)
}

export const offlineScanQueue = {
  enqueue,
  remove,
  markFailed,
  markPending,
  all: (): PendingScan[] => cache,
}
