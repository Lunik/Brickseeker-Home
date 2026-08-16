import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, ResolveResult } from '../api/types'
import { useSettings } from '../lib/settings-context'
import { formatDateTime } from '../lib/format'
import Icon from '../components/Icon'
import NotificationsBell from '../components/NotificationsBell'
import { ErrorLabel, Sheet, Spinner, StatCard } from '../components/ui'

interface HistoryPayload {
  sets: { setNum: string }[]
}

interface WishlistPayload {
  sets: { setNum: string }[]
  isLinked: boolean
}

interface StatsPayload {
  setCount: number
}

/**
 * The app root — and the app's only navigation hub, exactly as on iOS: every other screen is
 * reached from a tile here or from the floating scan cluster.
 *
 * Manual entry and photo import both resolve through `/scan/lookup`, the same path the camera
 * uses, rather than each having its own resolution logic.
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
  const scanEvents = useQuery({
    queryKey: ['scan-events'],
    queryFn: () => api.get<{ events: unknown[] }>('/history/events'),
  })
  const minifigs = useQuery({
    queryKey: ['minifig-count'],
    queryFn: () => api.get<{ count: number }>('/catalog/minifigs?ownedOnly=true&limit=1'),
    retry: false,
  })
  const stats = useQuery({
    queryKey: ['stats-lite'],
    queryFn: () => api.get<StatsPayload>('/stats'),
    enabled: false,
  })

  const sync = useMutation({
    mutationFn: () => api.post<CollectionPayload>('/collection/sync'),
    onSuccess: async () => {
      // The gift list piggybacks on the same trigger, as on iOS — one "synchroniser" for the user,
      // two accounts underneath. Best-effort: a Brickset failure must not report the collection
      // sync as failed.
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
      if (!result.setNums.length) throw new Error('Aucun numéro de set lisible sur cette photo.')
      return result.setNums[0]
    },
    onSuccess: (setNum) => lookup.mutate({ setNum, source: 'photoImport' }),
    onError: (error: Error) => setLookupError(error.message),
  })

  const credentials = settings?.credentials
  const isLinked = credentials?.rebrickableLinked ?? false
  const bricksetLinked = wishlist.data?.isLinked ?? credentials?.bricksetLinked ?? false
  const lastSyncedAt = collection.data?.lastSyncedAt ?? null

  // Every branch renders exactly one line, blank included, so the row never appears and
  // disappears under the content while a pull-to-refresh gesture is still tracking.
  const syncLine = sync.isPending ? (
    <span className="flex items-center gap-2 text-[13px] text-ink-muted">
      <Spinner className="h-3 w-3" /> Synchronisation…
    </span>
  ) : sync.isError ? (
    <ErrorLabel message={(sync.error as Error).message} className="text-[13px]" />
  ) : lastSyncedAt ? (
    <span className="text-[13px] text-ink-faint">
      Dernière synchronisation : {formatDateTime(lastSyncedAt)}
    </span>
  ) : (
    <span className="text-[13px]">&nbsp;</span>
  )

  return (
    <div className="space-y-7 pb-40">
      {/* Floating circular controls over the content, as on iOS — not a header bar. */}
      <div className="flex justify-end gap-2 pt-2">
        {isLinked && (
          <button
            type="button"
            className="nav-circle"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            aria-label="Synchroniser"
          >
            {sync.isPending ? <Spinner className="h-5 w-5" /> : <Icon name="refresh" className="h-6 w-6" />}
          </button>
        )}
        <NotificationsBell />
        <Link to="/settings" className="nav-circle" aria-label="Réglages">
          <Icon name="settings" className="h-6 w-6" />
        </Link>
      </div>

      <h1 className="text-[34px] font-bold leading-tight text-ink">BrickSeeker</h1>

      {credentials && !credentials.rebrickableApiKey && (
        <Link
          to="/settings"
          className="flex items-center gap-2 rounded-xl bg-[rgb(var(--warning))] px-3 py-3 text-[15px] font-semibold text-black"
        >
          <Icon name="warning" className="h-4 w-4" />
          Clé API Rebrickable non configurée
          <Icon name="chevron-right" className="ml-auto h-4 w-4" />
        </Link>
      )}

      <section className="space-y-3">
        <h2 className="text-[22px] font-bold text-ink">Activité</h2>
        <div className="grid grid-cols-2 gap-3">
          <Link to="/history">
            <StatCard
              title="Sets scannés"
              value={String(history.data?.sets.length ?? 0)}
              icon={<Icon name="hash" className="h-7 w-7" />}
              isLink
            />
          </Link>
          <StatCard
            title="Scans effectués"
            value={String(scanEvents.data?.events.length ?? 0)}
            icon={<Icon name="viewfinder" className="h-7 w-7" />}
          />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-[22px] font-bold text-ink">Collection</h2>
        {!isLinked ? (
          <p className="text-[15px] text-ink-muted">
            Compte non lié — ouvrez{' '}
            <Link to="/settings" className="font-semibold text-brand">
              Paramètres
            </Link>{' '}
            pour lier votre compte Rebrickable.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Link to="/stats">
                <StatCard
                  title="Statistiques"
                  icon={<Icon name="chart" className="h-7 w-7" />}
                  caption="Voir le détail"
                  isLink
                />
              </Link>
              <Link to="/collection">
                <StatCard
                  title="Sets possédés"
                  value={String(collection.data?.sets.length ?? stats.data?.setCount ?? 0)}
                  icon={<Icon name="box" className="h-7 w-7" />}
                  isLink
                />
              </Link>
              <Link to="/minifigs">
                <StatCard
                  title="Mes minifigs"
                  value={String(minifigs.data?.count ?? 0)}
                  icon={<Icon name="user" className="h-7 w-7" />}
                  isLink
                />
              </Link>
              <Link to="/new-sets">
                <StatCard
                  title="Nouveaux sets"
                  icon={<Icon name="sparkles" className="h-7 w-7" />}
                  caption="Voir le détail"
                  isLink
                />
              </Link>
            </div>
            {syncLine}
          </>
        )}
      </section>

      {/* Gated on its own account: the gift list lives on Brickset, not Rebrickable. */}
      <section className="space-y-3">
        <h2 className="text-[22px] font-bold text-ink">Liste cadeaux</h2>
        {!bricksetLinked ? (
          <p className="text-[15px] text-ink-muted">
            Compte non lié — ouvrez{' '}
            <Link to="/settings" className="font-semibold text-brand">
              Paramètres
            </Link>{' '}
            pour lier votre compte Brickset.
          </p>
        ) : (
          <>
            <Link to="/wishlist" className="block">
              <StatCard
                title="Dans la liste cadeaux"
                value={String(wishlist.data?.sets.length ?? 0)}
                icon={<Icon name="heart" className="h-7 w-7" />}
                isLink
              />
            </Link>
            {syncLine}
          </>
        )}
      </section>

      {lookupError && <ErrorLabel message={lookupError} />}

      {/* The cluster floats over the content with no backing of its own: a panel behind it left a
          dead strip of page background on iOS, and would here too. */}
      <div className="fixed inset-x-0 bottom-8 z-20 mx-auto flex w-full max-w-2xl items-center justify-center gap-6">
        <button
          type="button"
          className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-raised text-brand shadow-lg"
          onClick={() => fileInput.current?.click()}
          aria-label="Depuis mes photos"
          disabled={ocr.isPending}
        >
          {ocr.isPending ? <Spinner className="h-6 w-6" /> : <Icon name="image" className="h-6 w-6" />}
        </button>
        <button
          type="button"
          className="flex h-[72px] w-[72px] items-center justify-center rounded-full bg-brand text-white shadow-xl"
          onClick={() => navigate('/scan')}
          aria-label="Scanner un set"
        >
          <Icon name="camera" className="h-8 w-8" />
        </button>
        <button
          type="button"
          className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-raised text-brand shadow-lg"
          onClick={() => setShowManualEntry(true)}
          aria-label="Saisie manuelle"
        >
          <Icon name="keyboard" className="h-6 w-6" />
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
          <input
            className="input"
            // Focused on open so the keyboard is already up, as the iOS sheet takes care to do.
            autoFocus
            inputMode="numeric"
            placeholder="Numéro du set (ex. 10307)"
            value={manualValue}
            onChange={(event) => setManualValue(event.target.value)}
          />
          <button type="submit" className="btn-primary w-full" disabled={lookup.isPending}>
            {lookup.isPending ? <Spinner className="h-5 w-5" /> : 'Rechercher'}
          </button>
          {lookupError && <ErrorLabel message={lookupError} />}
        </form>
      </Sheet>
    </div>
  )
}
