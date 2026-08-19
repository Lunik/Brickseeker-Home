import { CacheableResponsePlugin } from 'workbox-cacheable-response'
import { ExpirationPlugin } from 'workbox-expiration'
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { CacheFirst, NetworkFirst } from 'workbox-strategies'

// The build-time-generated, content-hashed list of the app shell (JS/CSS/HTML, icons, the
// tesseract assets) — this is what lets the app load with zero network after a first visit.
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Every in-app route is client-side: only `/` exists as a real document, so a reload or a deep
// link on `/history`, `/collection` or `/set/10307-1` asks the network for a path the precache has
// no entry for, and offline that is a browser error page rather than the app. Serving the shell
// for any navigation is the SPA counterpart of `main.py`'s own server-side fallback — without it
// the app is offline-capable at exactly one URL.
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('index.html'), {
    // `/api/...` is never a navigation, but an explicit denylist keeps a future non-SPA path
    // (a CSV export opened in a tab) from being answered with the app shell.
    denylist: [/^\/api\//],
  }),
)

//: Data worth reading offline. Anchored per segment so `sets` can't also match `settings`.
const CACHEABLE_API =
  /^\/api\/(collection|history|wishlist|sets|minifigs|prices|alerts|stats|settings|catalog)(\/|$)/
//: Carved back out of the above. `catalog/export` is pulled into IndexedDB by application code and
//: has no business being duplicated in the HTTP cache; the rest are transient progress reads and
//: file downloads, where a cached answer is actively misleading — the same reason
//: `lib/query-persistence.ts` refuses to persist them.
const UNCACHEABLE_API = /^\/api\/(catalog\/export|prices\/batch|wishlist\/import|stats\/export)/

// Live data wins whenever the LAN server answers; a cached response serves the moment it doesn't
// (or answers slowly — 4s is "don't let a hung request stall the UI", not a real timeout). Only
// GET is ever matched here, so no mutation response is ever cached.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    CACHEABLE_API.test(url.pathname) &&
    !UNCACHEABLE_API.test(url.pathname),
  new NetworkFirst({
    cacheName: 'brickseeker-api-v1',
    networkTimeoutSeconds: 4,
    plugins: [new CacheableResponsePlugin({ statuses: [200] })],
  }),
)

// Catalogue artwork, fetched by the browser straight from the Rebrickable/Brickset/BrickLink CDNs.
// This used to rely on the browser's own HTTP cache instead of Cache Storage — those CDNs send
// `max-age=31536000`, so in principle no revalidation is ever needed. In practice, iOS's WKWebView
// HTTP cache is far smaller and evicted far more aggressively than desktop browsers': artwork shown
// minutes earlier over Wi-Fi was already gone once the phone went offline, leaving every row in the
// list blank. Cache Storage survives that. None of these CDNs send CORS headers, so every response
// here is opaque (status 0) — `CacheableResponsePlugin` explicitly allows that through, since the
// default cacheable check requires `200`.
registerRoute(
  ({ request, url }) => request.destination === 'image' && url.origin !== self.location.origin,
  new CacheFirst({
    cacheName: 'brickseeker-artwork-v1',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      // Bounded mainly by count, not age: this artwork doesn't change once a set exists, so the
      // CDN's own year-long `max-age` is matched here rather than invented — the real limit on a
      // large collection is disk space, not staleness.
      new ExpirationPlugin({ maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 365 }),
    ],
  }),
)

// Push notifications only below this line — unchanged from before this file gained caching.
//
// Without `skipWaiting`/`clients.claim`, a tab opened before this worker activated stays
// *uncontrolled* — `matchAll` still returns it (`includeUncontrolled: true`), but
// `WindowClient.navigate()` on an uncontrolled client rejects per spec, so the very first
// notification tap after install silently failed to deep-link and only focused whatever screen
// was already open.
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let payload = { title: 'BrickSeeker', body: '', setNum: null }
  try {
    if (event.data) payload = { ...payload, ...event.data.json() }
  } catch {
    payload.body = event.data ? event.data.text() : ''
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/icons/icon-192.png',
      // Deliberately still the plain mark, not the artwork: a badge is flattened to a silhouette,
      // so a detailed illustration arrives as a solid blob.
      badge: '/favicon.svg',
      tag: payload.setNum ? `set-${payload.setNum}` : 'brickseeker',
      data: { url: payload.setNum ? `/set/${encodeURIComponent(payload.setNum)}` : '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = event.notification.data?.url ?? '/'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus an open tab rather than opening a second copy of the app. `navigate()` rejects on an
      // uncontrolled client (or one that no longer exists by the time this runs) — fall back to
      // opening a fresh window rather than leaving the notification silently unhandled.
      for (const client of clients) {
        if ('focus' in client && 'navigate' in client) {
          return client
            .navigate(target)
            .then((navigated) => navigated.focus())
            .catch(() => self.clients.openWindow(target))
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
