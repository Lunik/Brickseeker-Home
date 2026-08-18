import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { SetRow } from '../api/types'
import ListPickerSheet from '../components/ListPickerSheet'
import ScanMap from '../components/ScanMap'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState, NavBar } from '../components/ui'
import { useSetActions } from '../hooks/useSetActions'
import { formatRelative } from '../lib/format'

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
