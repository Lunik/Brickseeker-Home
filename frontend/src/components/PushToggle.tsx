import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { ErrorLabel } from './ui'

/** base64url → Uint8Array, the form `applicationServerKey` requires. */
function decodeVapidKey(base64: string): Uint8Array<ArrayBuffer> {
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index)
  return bytes
}

/**
 * Web Push opt-in.
 *
 * Push is the optional half of notifications: the in-app bell works regardless, so an
 * unsupported browser gets an explanation rather than a broken toggle. Safari in particular only
 * exposes push once the app has been installed to the home screen.
 */
export default function PushToggle() {
  const supported =
    typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window
  const [subscribed, setSubscribed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!supported) return
    void navigator.serviceWorker
      .getRegistration()
      .then((registration) => registration?.pushManager.getSubscription())
      .then((subscription) => setSubscribed(Boolean(subscription)))
      .catch(() => undefined)
  }, [supported])

  async function enable() {
    setBusy(true)
    setError(null)
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') throw new Error('Notifications refusées par le navigateur.')

      const registration = await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
      const { publicKey } = await api.get<{ publicKey: string }>('/notifications/vapid-key')
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeVapidKey(publicKey),
      })
      await api.post('/notifications/subscribe', subscription.toJSON())
      setSubscribed(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Activation impossible')
    } finally {
      setBusy(false)
    }
  }

  async function disable() {
    setBusy(true)
    try {
      const registration = await navigator.serviceWorker.getRegistration()
      const subscription = await registration?.pushManager.getSubscription()
      if (subscription) {
        await api.post('/notifications/unsubscribe', { endpoint: subscription.endpoint })
        await subscription.unsubscribe()
      }
      setSubscribed(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Désactivation impossible')
    } finally {
      setBusy(false)
    }
  }

  if (!supported) {
    return (
      <p className="text-xs text-ink-faint">
        Ce navigateur ne gère pas les notifications push (sur iOS, il faut d'abord ajouter
        BrickSeeker à l'écran d'accueil). Les notifications restent visibles dans la cloche.
      </p>
    )
  }

  return (
    <div className="space-y-1.5">
      <button
        type="button"
        className={subscribed ? 'btn-secondary w-full' : 'btn-primary w-full'}
        disabled={busy}
        onClick={() => void (subscribed ? disable() : enable())}
      >
        {subscribed ? 'Désactiver les notifications push' : 'Activer les notifications push'}
      </button>
      {error && <ErrorLabel message={error} />}
    </div>
  )
}
