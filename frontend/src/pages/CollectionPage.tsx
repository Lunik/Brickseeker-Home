import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, SetRow } from '../api/types'
import ListConditionsSheet from '../components/ListConditionsSheet'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState, Sheet } from '../components/ui'
import { formatDateTime } from '../lib/format'

export default function CollectionPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showLists, setShowLists] = useState(false)
  const [moveTarget, setMoveTarget] = useState<string[] | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
  })

  const sync = useMutation({
    mutationFn: () => api.post<CollectionPayload>('/collection/sync'),
    onSuccess: () => queryClient.invalidateQueries(),
  })

  interface BulkResult {
    succeeded: string[]
    failed: { setNum: string; error: string }[]
  }

  /** A 200 with a non-empty `failed` list is a partial failure, not a success. */
  function assertNoFailures(result: BulkResult) {
    if (result.failed?.length) {
      throw new Error(
        `${result.failed.length} set(s) n'ont pas pu être traités. Vérifiez votre connexion.`,
      )
    }
  }

  async function bulkRemove(setNums: string[]) {
    const result = await api.post<BulkResult>('/collection/bulk', { setNums, action: 'remove' })
    await queryClient.invalidateQueries()
    assertNoFailures(result)
  }

  async function bulkMove(setNums: string[], listId: number) {
    const result = await api.post<BulkResult>('/collection/bulk', { setNums, action: 'move', listId })
    await queryClient.invalidateQueries()
    assertNoFailures(result)
  }

  async function refreshPrices(setNums: string[]) {
    const { status } = await api.post<{ status: string }>('/prices/batch/start', { setNums })
    await queryClient.invalidateQueries({ queryKey: ['priceBatch'] })
    if (status === 'busy') {
      throw new Error('Une actualisation des prix est déjà en cours — réessayez ensuite.')
    }
  }

  const actions: BulkAction[] = [
    { key: 'prices', label: 'Rafraîchir les prix', run: refreshPrices },
    {
      key: 'move',
      label: 'Déplacer…',
      run: async (setNums) => setMoveTarget(setNums),
    },
    {
      key: 'remove',
      label: 'Retirer de la collection',
      destructive: true,
      confirm: (count) =>
        `${count} set(s) seront retirés de votre collection Rebrickable. Les scans, prix payés et alertes sont conservés.`,
      run: bulkRemove,
    },
  ]

  const lists = data?.lists ?? []

  return (
    <>
      <SetListScreen
        title="Ma collection"
        screenId="collection"
        rows={data?.sets ?? []}
        isLoading={isLoading}
        error={error ? (error as Error).message : null}
        showLists
        subtitleFor={(row: SetRow) =>
          [row.currentListName, row.themeName, row.year || null].filter(Boolean).join(' · ')
        }
        bulkActions={actions}
        onOpenSet={(row, visible) =>
          navigate(`/set/${encodeURIComponent(row.setNum)}`, {
            state: { siblings: visible.map((item) => item.setNum) },
          })
        }
        onRefresh={() => (data?.isLinked ? sync.mutate() : refetch())}
        isRefreshing={sync.isPending || isFetching}
        navActions={
          lists.length > 0 ? (
            <button
              type="button"
              className="nav-circle"
              onClick={() => setShowLists(true)}
              aria-label="Types de listes (neuf/occasion)"
            >
              <Icon name="tag" />
            </button>
          ) : undefined
        }
        header={
          data?.lastSyncedAt ? (
            <p className="px-1 text-[13px] text-ink-faint">
              Synchronisé {formatDateTime(data.lastSyncedAt)}
            </p>
          ) : undefined
        }
        emptyState={
          !data?.isLinked ? (
            <EmptyState
              icon={<Icon name="link" className="h-9 w-9" />}
              title="Compte Rebrickable non lié"
              message="Liez votre compte dans les Paramètres pour retrouver votre collection ici."
              action={
                <button type="button" className="btn-primary" onClick={() => navigate('/settings')}>
                  Ouvrir les Paramètres
                </button>
              }
            />
          ) : (
            <EmptyState
              icon={<Icon name="box" className="h-9 w-9" />}
              title="Aucun set dans votre collection"
              message="Synchronisez pour récupérer ce que vous possédez sur Rebrickable."
              action={
                <button type="button" className="btn-primary" onClick={() => sync.mutate()}>
                  Synchroniser
                </button>
              }
            />
          )
        }
      />

      <ListConditionsSheet open={showLists} onClose={() => setShowLists(false)} />

      <Sheet
        open={moveTarget !== null}
        title="Déplacer vers une liste"
        onClose={() => setMoveTarget(null)}
      >
        <div className="space-y-2">
          {lists.map((list) => (
            <button
              key={list.id}
              type="button"
              className="btn-secondary w-full"
              onClick={async () => {
                if (moveTarget) await bulkMove(moveTarget, list.id)
                setMoveTarget(null)
              }}
            >
              {list.name}
            </button>
          ))}
        </div>
      </Sheet>
    </>
  )
}
