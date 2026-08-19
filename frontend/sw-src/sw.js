import { CacheableResponsePlugin } from 'workbox-cacheable-response'
import { ExpirationPlugin } from 'workbox-expiration'
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'
import { registerRoute } from 'workbox-routing'
import { CacheFirst, NetworkFirst } from 'workbox-strategies'

// The build-time-generated, content-hashed list of the app shell (JS/CSS/HTML, icons, the
// tesseract assets) — this is what lets the app load with zero network after a first visit.
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Live data wins whenever the LAN server answers; a cached response serves the moment it doesn't
// (or answers slowly — 4s is "don't let a hung request stall the UI", not a real timeout). Only
// GET is ever matched here, so no mutation response is ever cached.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /^\/api\/(collection|history|wishlist|new-sets|minifigs|prices|sets|catalog\/status)/.test(
      url.pathname,
    ),
  new NetworkFirst({
    cacheName: 'brickseeker-api-v1',
    networkTimeoutSeconds: 4,
    plugins: [new CacheableResponsePlugin({ statuses: [200] })],
  }),
)

// The backend already sends `Cache-Control: public, max-age=604800, immutable` for a given image
// URL — this makes that guarantee durable under Service Worker control rather than relying on the
// browser's plain HTTP cache, which private mode or storage pressure can evict independently.
registerRoute(
  ({ url, request }) => request.method === 'GET' && url.pathname === '/api/images',
  new CacheFirst({
    cacheName: 'brickseeker-images-v1',
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 800, maxAgeSeconds: 60 * 60 * 24 * 30 }),
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
      icon: '/favicon.svg',
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
