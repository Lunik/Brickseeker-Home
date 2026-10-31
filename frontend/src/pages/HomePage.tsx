import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, CollectionStats, ResolveResult } from '../api/types'
import { useSettings } from '../lib/settings-context'
import { formatDateTime, formatEUR } from '../lib/format'
import Icon, { type IconName } from '../components/Icon'
import BlockedPricesButton from '../components/BlockedPricesButton'
import NotificationsBell from '../components/NotificationsBell'
import { ErrorLabel, ProgressBar, Spinner, StatCard } from '../components/ui'

interface HistoryPayload {
  sets: { setNum: string }[]
}

interface WishlistPayload {
  sets: { setNum: string }[]
  isLinked: boolean
}

/**
 * The app root — and the app's only navigation hub, exactly as on iOS: every other screen is
 * reached from a tile here or from the floating scan cluster.
 *
 * Manual entry is the only way to look a set up; it resolves through `/scan/lookup`.
 */
export default function HomePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { settings } = useSettings()
  const [manualValue, setManualValue] = useState('')
  const [lookupError, setLookupError] = useState<string | null>(null)

  const isLinkedEarly = settings?.credentials?.rebrickableLinked ?? false

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
    queryKey: ['stats'],
    queryFn: () => api.get<CollectionStats>('/stats'),
    enabled: isLinkedEarly,
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
        <BlockedPricesButton />
        <NotificationsBell />
        <Link to="/settings" className="nav-circle lg:hidden" aria-label="Paramètres">
          <Icon name="settings" className="h-6 w-6" />
        </Link>
      </div>

      <h1 className="text-[36px] lg:hidden font-extrabold leading-tight tracking-tight text-ink">BrickSeeker</h1>

      <form
        className="relative"
        onSubmit={(event) => {
          event.preventDefault()
          if (manualValue.trim()) lookup.mutate({ setNum: manualValue.trim(), source: 'manualEntry' })
        }}
      >
        <Icon name="search" className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
        <input
          className="search-field pr-24"
          inputMode="numeric"
          placeholder="Numéro de set, ex. 10307"
          aria-label="Numéro du set"
          value={manualValue}
          onChange={(event) => setManualValue(event.target.value)}
        />
        <button
          type="submit"
          className="absolute right-1 top-1/2 flex h-10 -translate-y-1/2 items-center rounded-full bg-brand px-4 text-[15px] font-semibold text-white"
          disabled={lookup.isPending}
        >
          {lookup.isPending ? <Spinner className="h-4 w-4" /> : 'Ouvrir'}
        </button>
      </form>
      {lookupError && <ErrorLabel message={lookupError} className="-mt-4" />}

      {stats.data && stats.data.setCount > 0 && <ValueHero stats={stats.data} />}

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
        <h2 className="text-[22px] font-bold tracking-tight text-ink">Collection</h2>
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
              <Link to="/collection">
                <StatCard
                  title="Sets possédés"
                  value={String(collection.data?.sets.length ?? 0)}
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
            </div>
            <div className="list-card">
              <HomeLink to="/stats" icon="chart" label="Statistiques" />
              <HomeLink to="/new-sets" icon="sparkles" label="Nouveaux sets" />
            </div>
            {syncLine}
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-[22px] font-bold tracking-tight text-ink">Activité</h2>
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
      {/* Gated on its own account: the gift list lives on Brickset, not Rebrickable. */}
      <section className="space-y-3">
        <h2 className="text-[22px] font-bold tracking-tight text-ink">Liste cadeaux</h2>
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

          </div>
  )
}

/** The headline of the dashboard: what the collection is worth and which way it is moving. */
function ValueHero({ stats }: { stats: CollectionStats }) {
  const points = stats.valueSnapshots.filter((snapshot) => snapshot.isReliable).map((snapshot) => snapshot.totalValueEur)
  const previous = points.length > 1 ? points[points.length - 2] : null
  const delta = previous ? stats.totalValueEur - previous : null

  const width = 120
  const height = 40
  const [min, max] = [Math.min(...points), Math.max(...points)]
  const path = points
    .map((value, i) => {
      const x = (i / Math.max(points.length - 1, 1)) * width
      const y = height - 4 - ((value - min) / Math.max(max - min, 1)) * (height - 8)
      return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <Link to="/stats" className="card block">
      <p className="section-title">Valeur de la collection</p>
      <div className="mt-2 flex items-end justify-between gap-4">
        <div>
          <p className="text-[34px] font-extrabold leading-none tracking-tight text-ink">{formatEUR(stats.totalValueEur)}</p>
          {delta !== null && delta !== 0 && (
            <p
              className={`mt-2 text-[14px] font-semibold ${
                delta > 0 ? 'text-[rgb(var(--positive))]' : 'text-[rgb(var(--negative))]'
              }`}
            >
              {delta > 0 ? '▲' : '▼'} {formatEUR(Math.abs(delta))} depuis la dernière mesure
            </p>
          )}
          {/* An estimated total is only honest next to its coverage (same wording as Statistiques),
              so the coverage sits right under the figure, with a gauge, at a readable size. */}
          <p className="mt-2 text-[14px] text-ink-muted">
            Estimée sur {stats.setsWithKnownPrice} / {stats.setCount} sets dont le prix est connu
          </p>
          <div className="mt-2 w-48 max-w-full">
            <ProgressBar value={stats.setsWithKnownPrice} total={stats.setCount} />
          </div>
          {stats.completablePriceCount > 0 && (
            <p className="mt-2 text-[14px] font-semibold text-brand">Compléter les prix manquants ›</p>
          )}
        </div>
        {points.length > 1 && (
          <svg viewBox={`0 0 ${width} ${height}`} className="h-10 w-28 shrink-0 text-brand" aria-hidden="true">
            <path d={path} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
    </Link>
  )
}

function HomeLink({ to, icon, label }: { to: string; icon: IconName; label: string }) {
  return (
    <Link
      to={to}
      className="flex min-h-14 items-center gap-3 border-b border-line/60 px-4 last:border-0 transition-colors hover:bg-surface-sunken/60 active:bg-surface-sunken"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand/10 text-brand">
        <Icon name={icon} className="h-5 w-5" />
      </span>
      <span className="flex-1 text-[17px] font-semibold text-ink">{label}</span>
      <Icon name="chevron-right" className="h-4 w-4 text-ink-faint" />
    </Link>
  )
}
