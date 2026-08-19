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
