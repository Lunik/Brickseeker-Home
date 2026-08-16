import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { SetRow } from '../api/types'
import ListPickerSheet from '../components/ListPickerSheet'
import ScanMap from '../components/ScanMap'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState } from '../components/ui'
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
      destructive: true,
      // A set still owned only loses its "scanned" flag — say so, rather than implying the set is
      // deleted outright.
      confirm: (count) =>
        `${count} set(s) quitteront l'historique. Ceux que tu possèdes restent dans ta collection.`,
      run: async (setNums) => {
        await remove.mutateAsync(setNums)
      },
    },
  ]

  if (showMap) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-[34px] font-bold leading-tight text-ink">Carte des scans</h1>
          <button type="button" className="btn-secondary" onClick={() => setShowMap(false)}>
            Liste
          </button>
        </div>
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
      header={
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowMap(true)}>
          <Icon name="map" className="mr-1 inline h-4 w-4 align-text-bottom" />
          Voir la carte des scans
        </button>
      }
      emptyState={
        <EmptyState
          icon={<Icon name="clock" className="h-9 w-9" />}
          title="Aucun scan pour l'instant"
          message="Les sets que tu scannes apparaîtront ici, avec l'endroit où tu les as vus si tu actives la localisation."
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
