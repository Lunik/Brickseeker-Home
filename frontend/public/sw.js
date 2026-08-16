// Push notifications only. Deliberately no offline caching: this app's data is live (prices,
// collection status) and a cached API response would be worse than no answer at all.

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
      // Focus an open tab rather than opening a second copy of the app.
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(target)
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
