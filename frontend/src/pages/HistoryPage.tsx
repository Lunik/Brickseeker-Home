import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { SetRow } from '../api/types'
import ListPickerSheet from '../components/ListPickerSheet'
import ScanMap from '../components/ScanMap'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState, NavBar, SetThumbnail, Spinner } from '../components/ui'
import { useSetActions } from '../hooks/useSetActions'
import { formatRelative } from '../lib/format'
import { offlineScanQueue, usePendingScans } from '../lib/offline-scan-queue'
import { syncPendingScans } from '../lib/offline-scan-sync'

export default function HistoryPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showMap, setShowMap] = useState(false)
  const actions = useSetActions()

  const { data, isLoading, error } = useQuery({
    queryKey: ['history'],
    queryFn: () => api.get<{ sets: SetRow[] }>('/history'),
  })

  const remove = useMutation({
    mutationFn: (setNums: string[]) =>
      Promise.all(setNums.map((setNum) => api.delete(`/history/${encodeURIComponent(setNum)}`))),
    onSuccess: () => queryClient.invalidateQueries(),
  })

  const bulkActions: BulkAction[] = [
    actions.refreshPrices,
    actions.addToCollection,
    actions.addToWishlist,
    {
      key: 'delete',
      label: 'Retirer tous les scans',
      icon: 'trash',
      destructive: true,
      // A set still owned only loses its "scanned" flag — say so, rather than implying the set is
      // deleted outright.
      confirm: (count) =>
        `${count} set(s) quitteront l'historique. Ceux que vous possédez restent dans votre collection.`,
      run: async (setNums) => {
        await remove.mutateAsync(setNums)
      },
    },
  ]

  if (showMap) {
    return (
      <div className="space-y-3">
        <NavBar
          title="Carte des scans"
          onBack={() => setShowMap(false)}
          backLabel="Retour à la liste"
          actions={
            <button type="button" className="nav-pill" onClick={() => setShowMap(false)}>
              Liste
            </button>
          }
        />
        <ScanMap />
      </div>
    )
  }

  return (
    <>
    <SetListScreen
      title="Historique"
      screenId="history"
      rows={data?.sets ?? []}
      isLoading={isLoading}
      error={error ? (error as Error).message : null}
      header={<PendingSyncSection />}
      showOwnedFilter
      subtitleFor={(row) =>
        [row.lastScannedAt ? `Scanné ${formatRelative(row.lastScannedAt)}` : null, row.themeName]
          .filter(Boolean)
          .join(' · ')
      }
      bulkActions={bulkActions}
      onOpenSet={(row, visible) =>
        navigate(`/set/${encodeURIComponent(row.setNum)}`, {
          state: { siblings: visible.map((item) => item.setNum) },
        })
      }
      navActions={
        <button
          type="button"
          className="nav-circle"
          onClick={() => setShowMap(true)}
          aria-label="Carte des scans"
        >
          <Icon name="map" />
        </button>
      }
      emptyState={
        <EmptyState
          icon={<Icon name="clock" className="h-9 w-9" />}
          title="Aucun scan pour l'instant"
          message="Les sets que vous scannez apparaîtront ici, avec l'endroit où vous les avez vus si vous activez la localisation."
          action={
            <button type="button" className="btn-primary" onClick={() => navigate('/scan')}>
              Scanner un set
            </button>
          }
        />
      }
    />
    <ListPickerSheet
      open={actions.listPicker.open}
      onClose={actions.listPicker.cancel}
      onPick={actions.listPicker.pick}
    />
    </>
  )
}

/**
 * Scans resolved offline (camera or manual entry, via the on-device catalogue) that haven't been
 * replayed through `/scan/lookup` yet — no real `ScanEvent` exists for them until they are. Lives
 * here, not injected as synthetic rows into `SetListScreen`, since these entries semantically
 * belong to Historique but aren't shaped like a `SetRow` yet.
 */
function PendingSyncSection() {
  const items = usePendingScans()
  const [expanded, setExpanded] = useState(false)
  const [syncingNow, setSyncingNow] = useState(false)

  if (items.length === 0) return null

  const failedCount = items.filter((item) => item.status === 'failed').length

  return (
    <section className="card space-y-2">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2">
          <Icon name="clock" className="h-4 w-4 text-brand" />
          <span className="text-sm font-semibold text-ink">
            En attente de synchronisation ({items.length})
          </span>
        </span>
        <Icon
          name="chevron-right"
          className={`h-4 w-4 shrink-0 text-ink-faint transition-transform ${expanded ? 'rotate-90' : ''}`}
        />
      </button>
      <p className="text-xs text-ink-faint">
        Scanné(s) hors-ligne via le catalogue local — sera(ont) enregistré(s) dans l'historique dès
        le retour de la connexion.
        {failedCount > 0 && ` ${failedCount} en échec, à réessayer.`}
      </p>
      {expanded && (
        <>
          <ul className="divide-y divide-line">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 py-2">
                <SetThumbnail url={item.resolvedSet.setImgUrl} alt={item.resolvedSet.name} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink">{item.resolvedSet.setNum}</span>
                  <span className="block truncate text-[13px] text-ink-muted">{item.resolvedSet.name}</span>
                  <span className="block text-[11px] text-ink-faint">
                    {item.status === 'failed' ? (item.error ?? 'Échec') : 'En attente de connexion'}
                  </span>
                </span>
                {item.status === 'failed' && (
                  <button
                    type="button"
                    className="btn-ghost shrink-0 px-2 py-0.5 text-xs"
                    onClick={() => {
                      void offlineScanQueue.markPending(item.id).then(() => syncPendingScans())
                    }}
                  >
                    Réessayer
                  </button>
                )}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="btn-secondary w-full text-xs"
            disabled={syncingNow}
            onClick={() => {
              setSyncingNow(true)
              void syncPendingScans().finally(() => setSyncingNow(false))
            }}
          >
            {syncingNow ? <Spinner className="h-4 w-4" /> : 'Tout synchroniser'}
          </button>
        </>
      )}
    </section>
  )
}
