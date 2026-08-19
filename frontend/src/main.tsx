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
  // Whether this navigation was already under a service worker's control the instant this script
  // ran — true for a repeat visit with nothing new to fetch, false for the very first visit ever
  // (or the first load after the user cleared site data). Only in the former case does a later
  // `controllerchange` mean "a newer version just took over out from under code already sitting in
  // memory"; in the latter it's just the very first worker claiming an until-now-uncontrolled tab,
  // and reloading a page that only just finished loading would be pure noise.
  const hadController = Boolean(navigator.serviceWorker.controller)

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then((registration) => {
      // A browser tab only checks for a new sw.js on its own schedule (roughly once a day, or on
      // a fresh navigation) — for an installed PWA that can sit open for days without either, that
      // makes "force a refresh when a new version is found" mean nothing until the browser gets
      // around to it. Checking whenever the tab regains focus catches an update the moment there's
      // actually someone there to see the refresh happen, rather than in the background hours
      // later.
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) void registration.update()
      })
    })
  })

  // The service worker's own `skipWaiting()`/`clients.claim()` (sw-src/sw.js) hand control of this
  // tab to the new version immediately, without waiting for it to be closed first — but that only
  // changes which worker answers future network requests; the HTML/JS this tab already evaluated
  // stays exactly as stale as it was. `controllerchange` is the moment that handover happens, and
  // reloading right then is what actually gets the tab onto the new code.
  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || reloading) return
    reloading = true
    window.location.reload()
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
