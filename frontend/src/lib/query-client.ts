/**
 * The one `QueryClient` instance, split out of `main.tsx` so non-component code (the offline-scan
 * sync engine) can invalidate queries after a background sync without needing React context.
 */

import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Price and collection data is expensive to fetch (scrapes, third-party APIs) and rarely
      // changes under the user's feet, so refetching on every window focus is pure waste here.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
      // Must be >= the persister's `maxAge` (see `main.tsx`). Only queries still held in the cache
      // are written to the persisted snapshot, and a query goes inactive the moment you navigate
      // away from its screen — at the 5-minute default, browsing Collection and pocketing the
      // phone for ten minutes garbage-collected it before it was ever persisted, so the offline
      // read it exists for found nothing.
      gcTime: 1000 * 60 * 60 * 24 * 7,
    },
  },
})
