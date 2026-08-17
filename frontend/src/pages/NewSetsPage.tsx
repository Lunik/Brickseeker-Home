import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, query } from '../api/client'
import type { CatalogStatus, SetRow } from '../api/types'
import ListPickerSheet from '../components/ListPickerSheet'
import SetListScreen from '../components/SetListScreen'
import { useSetActions } from '../hooks/useSetActions'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, Spinner } from '../components/ui'
import { formatDate } from '../lib/format'

interface CatalogSetRow {
  setNum: string
  name: string
  year: number
  themeId: number
  themeName: string
  numParts: number
  setImgUrl: string | null
  firstSeenAt: string | null
  isOwned: boolean
  availability: SetRow['availability']
  resolvedPrice: number | null
}

/** The catalogue browser. Its default sort is "date d'ajout" — when *this* install first saw the
 *  set — which is a truer "new" signal than the release year. */
export default function NewSetsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const actions = useSetActions()
  const pageSize = 60

  const status = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (q) => (q.state.data?.sets.status?.state === 'running' ? 2000 : false),
  })

  const hasCatalog = (status.data?.sets.rowCount ?? 0) > 0

  const { data, isLoading, error } = useQuery({
    queryKey: ['new-sets', page],
    queryFn: () =>
      api.get<{ count: number; results: CatalogSetRow[] }>(
        `/catalog/new-sets${query({ sort: 'dateAdded', ascending: false, offset: page * pageSize, limit: pageSize })}`,
      ),
    enabled: hasCatalog,
  })

  const download = useMutation({
    mutationFn: () => api.post('/catalog/sets/download'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog-status'] }),
  })

  const downloading = status.data?.sets.status?.state === 'running'
  const progress = status.data?.sets.status?.progress ?? 0

  if (!hasCatalog) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-ink">Nouveaux sets</h1>
        <EmptyState
          icon={<Icon name="sparkles" className="h-9 w-9" />}
          title="Catalogue non téléchargé"
          message="Téléchargez le catalogue Rebrickable (~28 000 sets) pour découvrir les nouveautés. Peut aussi se faire depuis les Paramètres."
          action={
            downloading ? (
              <span className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner className="h-4 w-4" /> Téléchargement… {Math.round(progress * 100)} %
              </span>
            ) : (
              <button
                type="button"
                className="btn-primary"
                onClick={() => download.mutate()}
                disabled={download.isPending}
              >
                Télécharger le catalogue
              </button>
            )
          }
        />
        {status.data?.sets.status?.state === 'error' && (
          <ErrorLabel message={status.data.sets.status.message ?? 'Téléchargement échoué'} />
        )}
      </div>
    )
  }

  // The catalogue rows are shaped for the shared list screen, which speaks `SetRow`.
  const rows: SetRow[] = (data?.results ?? []).map((row) => ({
    setNum: row.setNum,
    name: row.name,
    year: row.year,
    themeId: row.themeId,
    themeName: row.themeName,
    numParts: row.numParts,
    setImgUrl: row.setImgUrl,
    quantity: 1,
    isInCollection: row.isOwned,
    isInWishlist: false,
    hasPriceAlert: false,
    wasScanned: false,
    lastScannedAt: row.firstSeenAt,
    currentListId: null,
    currentListName: null,
    storePriceEur: row.resolvedPrice,
    availability: row.availability,
    resolvedPrice: row.resolvedPrice,
    priceCondition: null,
    priceLabel: null,
  }))

  const total = data?.count ?? 0
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1)

  return (
    <>
    <SetListScreen
      title="Nouveaux sets"
      screenId="new-sets"
      defaultSort="dateAdded"
      // A catalogue entry was never scanned, so that sort would mean nothing here.
      excludedSorts={['dateScanned']}
      bulkActions={[actions.refreshPrices, actions.addToCollection, actions.addToWishlist]}
      onRefresh={() => download.mutate()}
      isRefreshing={downloading}
      showOwnedFilter
      rows={rows}
      isLoading={isLoading}
      error={error ? (error as Error).message : null}
      subtitleFor={(row) =>
        [row.themeName, row.year || null, row.lastScannedAt ? `vu le ${formatDate(row.lastScannedAt)}` : null]
          .filter(Boolean)
          .join(' · ')
      }
      onOpenSet={(row, visible) =>
        navigate(`/set/${encodeURIComponent(row.setNum)}`, {
          state: { siblings: visible.map((item) => item.setNum) },
        })
      }
      header={
        // The catalogue is ~28 000 rows: paginated server-side rather than held in memory.
        total > pageSize ? (
          <div className="flex items-center gap-2 text-xs text-ink-faint">
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => setPage((value) => Math.max(0, value - 1))}
              disabled={page === 0}
            >
              <Icon name="chevron-left" className="mr-0.5 inline h-3.5 w-3.5" />
              Précédent
            </button>
            <span>
              Page {page + 1} / {lastPage + 1}
            </span>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => setPage((value) => Math.min(lastPage, value + 1))}
              disabled={page >= lastPage}
            >
              Suivant
              <Icon name="chevron-right" className="ml-0.5 inline h-3.5 w-3.5" />
            </button>
          </div>
        ) : undefined
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
