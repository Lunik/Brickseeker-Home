import { useState } from 'react'

import { api } from '../api/client'
import { ErrorLabel, Spinner } from '../components/ui'

/**
 * The password gate, shown only when BRICKSEEKER_PASSWORD is set.
 *
 * Renders *outside* the settings provider — settings need a session — so it cannot use
 * `useSettings` and deliberately keeps its own minimal styling.
 */
export default function LoginGate({ onSuccess }: { onSuccess: () => Promise<void> | void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/login', { password })
      await onSuccess()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Connexion impossible')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div className="space-y-1 text-center">
          <p className="text-2xl font-extrabold">
            Brick<span className="text-brand">Seeker</span>
          </p>
          <p className="text-sm text-ink-muted">Cette instance est protégée par un mot de passe.</p>
        </div>
        <label className="block space-y-1.5">
          <span className="section-title">Mot de passe</span>
          <input
            type="password"
            className="input"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && <ErrorLabel message={error} />}
        <button type="submit" className="btn-primary w-full" disabled={busy || !password}>
          {busy ? <Spinner className="h-4 w-4" /> : 'Se connecter'}
        </button>
      </form>
    </div>
  )
}
