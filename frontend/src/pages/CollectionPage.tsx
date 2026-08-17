import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, ListCondition, SetRow } from '../api/types'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState, Sheet } from '../components/ui'
import { CONDITION_LABEL, formatDateTime } from '../lib/format'

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

  const setCondition = useMutation({
    mutationFn: (payload: { listId: number; condition: ListCondition }) =>
      api.patch(`/collection/lists/${payload.listId}`, { condition: payload.condition }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['collection'] }),
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

      {/* The per-list condition has no Rebrickable equivalent: it is what decides whether a list's
          sets are valued as new (retail chain) or used (BrickLink occasion). */}
      <Sheet open={showLists} title="Conditions des listes" onClose={() => setShowLists(false)}>
        <p className="mb-3 text-sm text-ink-muted">
          La condition d'une liste décide de la source de prix utilisée pour valoriser les sets
          qu'elle contient.
        </p>
        <ul className="divide-y divide-line">
          {lists.map((list) => (
            <li key={list.id} className="flex items-center gap-3 py-3">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-ink">{list.name}</span>
                <span className="block text-xs text-ink-faint">{list.numSets} set(s)</span>
              </span>
              <select
                className="input w-auto"
                value={list.condition}
                onChange={(event) =>
                  setCondition.mutate({
                    listId: list.id,
                    condition: event.target.value as ListCondition,
                  })
                }
              >
                <option value="newSet">{CONDITION_LABEL.newSet}</option>
                <option value="used">{CONDITION_LABEL.used}</option>
              </select>
            </li>
          ))}
        </ul>
      </Sheet>

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
