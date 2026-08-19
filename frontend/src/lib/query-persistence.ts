/**
 * Which React Query caches survive a reload via IndexedDB (see `main.tsx`'s
 * `PersistQueryClientProvider`), so Collection/Historique/Liste cadeaux/the catalogue/prices can
 * be consulted offline — cache-first on display, live reconciliation the moment the server
 * answers again, never the other way round.
 *
 * Deliberately excluded:
 * - `auth-status` — must always be checked fresh. Persisting it would let a password-gated
 *   instance skip the login gate while offline.
 * - `priceBatch` / `wishlist-import` — transient progress polling, meaningless once persisted
 *   (a "63% done" restored from three days ago is worse than no reading at all).
 */

import { defaultShouldDehydrateQuery, type Query } from '@tanstack/react-query'

export const PERSISTED_QUERY_KEYS = [
  'settings',
  'collection',
  'history',
  'wishlist',
  'alerts',
  'stats',
  'scan-events',
  'minifig-count',
  'new-sets',
  'new-sets-filter-options',
  'minifigs',
  'minifigs-filter-options',
  'catalog-status',
  'prices',
  'set',
  'set-minifigs',
  'minifig-sets',
  'similar',
]

export function shouldPersistQuery(query: Query): boolean {
  return defaultShouldDehydrateQuery(query) && PERSISTED_QUERY_KEYS.includes(query.queryKey[0] as string)
}
