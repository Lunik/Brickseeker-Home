import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { del, get, set } from 'idb-keyval'

import App from './App'
import { initOfflineScanSync } from './lib/offline-scan-sync'
import { queryClient } from './lib/query-client'
import { shouldPersistQuery } from './lib/query-persistence'
import './index.css'

// IndexedDB, not localStorage: this cache is meant to hold Collection/Historique/prices/the
// catalogue, which is far more than localStorage's ~5-10MB synchronous store should carry.
const persister = createAsyncStoragePersister({
  key: 'brickseeker-query-cache',
  storage: {
    getItem: async (key: string) => (await get<string>(key)) ?? null,
    setItem: (key: string, value: string) => set(key, value),
    removeItem: (key: string) => del(key),
  },
})

// Eager, not just on push opt-in: this is what makes app-shell precaching and cached API/image
// responses apply to every visitor, not only the ones who enable notifications. Fire-and-forget on
// `load` so it never competes with first paint.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js')
  })
}

// Everything this app caches to work offline — the ~21 MB precache, the catalogue snapshot, the
// query cache, and above all the queue of scans not yet synced — is "best effort" storage by
// default, evictable under pressure. Eviction would strike precisely when it cannot be recovered:
// with no network to re-fetch from. Browsers grant this silently on an installed PWA and decline
// it elsewhere, so it is a request, not a guarantee, and nothing here depends on the answer.
void navigator.storage?.persist?.().catch(() => undefined)

// Registers the online/foreground/reachability triggers that replay scans queued while offline.
initOfflineScanSync()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        // Distinct from `staleTime` above: that governs "refetch on every navigation" while
        // online, this governs "how old can offline-restored data be before showing nothing beats
        // showing it" — a much longer horizon on purpose.
        maxAge: 1000 * 60 * 60 * 24 * 7,
        buster: 'v1',
        dehydrateOptions: { shouldDehydrateQuery: shouldPersistQuery },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PersistQueryClientProvider>
  </React.StrictMode>,
)
