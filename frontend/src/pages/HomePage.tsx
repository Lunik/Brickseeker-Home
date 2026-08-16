import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, ResolveResult } from '../api/types'
import { useSettings } from '../lib/settings-context'
import { formatDateTime } from '../lib/format'
import Icon from '../components/Icon'
import { ErrorLabel, Sheet, Spinner, StatCard } from '../components/ui'

interface HistoryPayload {
  sets: { setNum: string }[]
}

interface WishlistPayload {
  sets: { setNum: string }[]
  isLinked: boolean
}

/**
 * The app root: what you own, what you've scanned, and the three ways into a lookup.
 *
 * Manual entry and photo import both resolve through `/scan/lookup` — the same path the camera
 * uses — rather than each having its own resolution logic, exactly as the iOS app funnels every
 * entry point through one view model.
 */
export default function HomePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { settings } = useSettings()
  const [showManualEntry, setShowManualEntry] = useState(false)
  const [manualValue, setManualValue] = useState('')
  const [lookupError, setLookupError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const collection = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
  })
  const history = useQuery({
    queryKey: ['history'],
    queryFn: () => api.get<HistoryPayload>('/history'),
  })
  const wishlist = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => api.get<WishlistPayload>('/wishlist'),
  })

  const sync = useMutation({
    mutationFn: () => api.post<CollectionPayload>('/collection/sync'),
    onSuccess: async () => {
      // The gift list piggybacks on the same trigger, as it does on iOS — one "synchroniser" for
      // the user, two accounts underneath. Best-effort: a Brickset failure must not report the
      // collection sync as failed.
      try {
        await api.post('/wishlist/sync')
      } catch {
        /* keep the last known wishlist state */
      }
      await queryClient.invalidateQueries()
    },
  })

  const lookup = useMutation({
    mutationFn: (payload: { setNum: string; source: string }) =>
      api.post<ResolveResult>('/scan/lookup', payload),
    onSuccess: (result) => {
      setLookupError(null)
      if (result.set) {
        setShowManualEntry(false)
        setManualValue('')
        navigate(`/set/${encodeURIComponent(result.set.setNum)}`)
      } else if (result.status === 'ambiguous') {
        setLookupError('Plusieurs sets correspondent — précise le numéro complet.')
      } else {
        setLookupError('Aucun set trouvé pour ce numéro.')
      }
    },
    onError: (error: Error) => setLookupError(error.message),
  })

  const ocr = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      const result = await api.upload<{ setNums: string[] }>('/scan/ocr', form)
      if (!result.setNums.length) throw new Error("Aucun numéro de set lisible sur cette photo.")
      return result.setNums[0]
    },
    onSuccess: (setNum) => lookup.mutate({ setNum, source: 'photoImport' }),
    onError: (error: Error) => setLookupError(error.message),
  })

  const credentials = settings?.credentials
  const isLinked = credentials?.rebrickableLinked ?? false
  const bricksetLinked = wishlist.data?.isLinked ?? credentials?.bricksetLinked ?? false
  const lastSyncedAt = collection.data?.lastSyncedAt ?? null

  const syncLine = sync.isPending ? (
    <span className="flex items-center gap-2 text-xs text-ink-muted">
      <Spinner className="h-3 w-3" /> Synchronisation…
    </span>
  ) : sync.isError ? (
    <ErrorLabel message={(sync.error as Error).message} className="text-xs" />
  ) : lastSyncedAt ? (
    <span className="text-xs text-ink-faint">Dernière synchronisation : {formatDateTime(lastSyncedAt)}</span>
  ) : (
    // A blank line rather than nothing: the row must not appear and disappear under the content.
    <span className="text-xs">&nbsp;</span>
  )

  return (
    <div className="space-y-6 pb-8">
      {credentials && !credentials.rebrickableApiKey && (
        <Link
          to="/settings"
          className="flex items-center gap-2 rounded-xl bg-amber-500 px-3 py-2.5 text-sm font-semibold text-black"
        >
          <Icon name="warning" className="h-4 w-4" />
          Clé API Rebrickable non configurée
          <Icon name="chevron-right" className="ml-auto h-4 w-4" />
        </Link>
      )}

      <section className="space-y-3">
        <h2 className="section-title">Activité</h2>
        <div className="grid grid-cols-2 gap-3">
          <Link to="/history">
            <StatCard
              title="Sets scannés"
              value={String(history.data?.sets.length ?? 0)}
              icon={<Icon name="hash" />}
              isLink
            />
          </Link>
          <Link to="/alerts">
            <StatCard title="Alertes de prix" icon={<Icon name="bell" />} value="" isLink />
          </Link>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="section-title">Collection</h2>
        {!isLinked ? (
          <p className="text-sm text-ink-muted">
            Compte non lié — ouvre les{' '}
            <Link to="/settings" className="font-semibold text-brand underline">
              Réglages
            </Link>{' '}
            pour lier ton compte Rebrickable.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Link to="/stats">
                <StatCard title="Statistiques" icon={<Icon name="chart" />} caption="Voir le détail" isLink />
              </Link>
              <Link to="/collection">
                <StatCard
                  title="Sets possédés"
                  value={String(collection.data?.sets.length ?? 0)}
                  icon={<Icon name="box" />}
                  isLink
                />
              </Link>
              <Link to="/minifigs">
                <StatCard title="Mes minifigs" icon={<Icon name="user" />} caption="Voir la galerie" isLink />
              </Link>
              <Link to="/new-sets">
                <StatCard title="Nouveaux sets" icon={<Icon name="sparkles" />} caption="Voir le catalogue" isLink />
              </Link>
            </div>
            <div className="flex items-center gap-3">
              {syncLine}
              <button
                type="button"
                className="btn-ghost ml-auto px-2 py-1 text-xs"
                onClick={() => sync.mutate()}
                disabled={sync.isPending}
              >
                Synchroniser
              </button>
            </div>
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="section-title">Liste cadeaux</h2>
        {!bricksetLinked ? (
          <p className="text-sm text-ink-muted">
            Compte non lié — ouvre les{' '}
            <Link to="/settings" className="font-semibold text-brand underline">
              Réglages
            </Link>{' '}
            pour lier ton compte Brickset.
          </p>
        ) : (
          <Link to="/wishlist">
            <StatCard
              title="Dans la liste cadeaux"
              value={String(wishlist.data?.sets.length ?? 0)}
              icon={<Icon name="gift" />}
              isLink
            />
          </Link>
        )}
      </section>

      {lookupError && <ErrorLabel message={lookupError} />}

      {/* The action cluster floats over the content with no backing of its own: a fixed panel left
          a dead strip of window background under it on iOS, and the same applies here. */}
      <div className="fixed inset-x-0 bottom-20 z-20 mx-auto flex w-full max-w-3xl items-center justify-center gap-6">
        <button
          type="button"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-raised text-xl shadow-lg ring-1 ring-line"
          onClick={() => fileInput.current?.click()}
          aria-label="Depuis mes photos"
          disabled={ocr.isPending}
        >
          {ocr.isPending ? <Spinner className="h-5 w-5" /> : <Icon name="image" />}
        </button>
        <button
          type="button"
          className="flex h-16 w-16 items-center justify-center rounded-full bg-brand text-white shadow-xl"
          onClick={() => navigate('/scan')}
          aria-label="Scanner un set"
        >
          <Icon name="camera" className="h-7 w-7" />
        </button>
        <button
          type="button"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-raised text-xl shadow-lg ring-1 ring-line"
          onClick={() => setShowManualEntry(true)}
          aria-label="Saisie manuelle"
        >
          <Icon name="keyboard" />
        </button>
      </div>

      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) ocr.mutate(file)
          event.target.value = ''
        }}
      />

      <Sheet open={showManualEntry} title="Saisie manuelle" onClose={() => setShowManualEntry(false)}>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (manualValue.trim()) lookup.mutate({ setNum: manualValue.trim(), source: 'manualEntry' })
          }}
        >
          <label className="block space-y-1.5">
            <span className="section-title">Numéro du set</span>
            <input
              className="input"
              // Focused on open so the keyboard is already up — the same detail the iOS sheet
              // takes care to preserve.
              autoFocus
              inputMode="numeric"
              placeholder="10307"
              value={manualValue}
              onChange={(event) => setManualValue(event.target.value)}
            />
          </label>
          <button type="submit" className="btn-primary w-full" disabled={lookup.isPending}>
            {lookup.isPending ? <Spinner className="h-4 w-4" /> : 'Rechercher'}
          </button>
          {lookupError && <ErrorLabel message={lookupError} />}
        </form>
      </Sheet>
    </div>
  )
}
