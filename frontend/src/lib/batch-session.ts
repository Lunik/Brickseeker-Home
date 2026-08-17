/**
 * The sets accumulated by one "mode lot" sweep.
 *
 * This is a **module-level** store, not React state, for the same reason the filter state is one:
 * the scanner is a route, so opening a scanned set unmounts it. Holding the session inside
 * `ScannerPage` meant the list of everything just scanned was destroyed by the act of looking at
 * any of it — which is exactly what "je ne peux pas aller dans la liste que je viens de scanner"
 * describes. iOS never had the problem: its session lives on the view model, and the summary is a
 * sheet stacked over a camera that is never torn down.
 *
 * Mirrored to `sessionStorage` on every change. iOS lets a session die with the camera screen, but
 * a phone browser is one accidental pull-to-refresh away from losing a twenty-box shelf sweep, and
 * there is nothing server-side to rebuild it from — no endpoint knows what "this session" means.
 * Closing the tab still ends it.
 */

import { useSyncExternalStore } from 'react'

import type { LegoSet } from '../api/types'

const STORAGE_KEY = 'brickseeker.batch-session.v1'

function restore(): LegoSet[] {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : null
    // Anything unexpected in storage is dropped rather than crashing the scanner on load.
    return Array.isArray(parsed) ? (parsed as LegoSet[]).filter((item) => item && item.setNum) : []
  } catch {
    return []
  }
}

let items: LegoSet[] = restore()
/** The set list a price run was last started for — so re-opening the summary doesn't re-fire it. */
let pricedSignature: string | null = null
const listeners = new Set<() => void>()

function commit(next: LegoSet[]): void {
  items = next
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    /* private mode, quota, or no storage at all — the session just becomes memory-only */
  }
  for (const listener of listeners) listener()
}

export const batchSession = {
  items: (): LegoSet[] => items,

  /** `false` when the set was already in the session — the camera re-reads the same box constantly. */
  add(set: LegoSet): boolean {
    if (items.some((item) => item.setNum === set.setNum)) return false
    commit([...items, set])
    return true
  },

  remove(setNum: string): void {
    commit(items.filter((item) => item.setNum !== setNum))
  },

  clear(): void {
    pricedSignature = null
    commit([])
  },

  /** Identity of the current session, so "have these already been priced?" is one comparison. */
  signature: (): string => items.map((item) => item.setNum).join(','),

  hasPriced(signature: string): boolean {
    return pricedSignature === signature
  },

  markPriced(signature: string): void {
    pricedSignature = signature
  },
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange)
  return () => {
    listeners.delete(onStoreChange)
  }
}

/** `items` is replaced, never mutated, so this reference is stable between changes. */
const snapshot = () => items

export function useBatchSession(): LegoSet[] {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
