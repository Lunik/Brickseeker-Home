// Push notifications only. Deliberately no offline caching: this app's data is live (prices,
// collection status) and a cached API response would be worse than no answer at all.

// Without these, a tab opened before this worker activated stays *uncontrolled* — `matchAll`
// still returns it (`includeUncontrolled: true`), but `WindowClient.navigate()` on an uncontrolled
// client rejects per spec, so the very first notification tap after install silently failed to
// deep-link and only focused whatever screen was already open.
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
