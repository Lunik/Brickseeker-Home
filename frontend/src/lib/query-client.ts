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
    },
  },
})
