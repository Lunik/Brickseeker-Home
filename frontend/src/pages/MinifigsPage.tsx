import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, imageUrl, query } from '../api/client'
import type { CatalogStatus, MinifigRow, SetRow } from '../api/types'
import Icon from '../components/Icon'
import SetListScreen from '../components/SetListScreen'
import { EmptyState, ErrorLabel, Spinner } from '../components/ui'
import { formatEUR } from '../lib/format'

/**
 * The owned-minifig gallery — the same browse screen as the lists, with a grid of cards instead of
 * rows. Built on `SetListScreen` rather than hand-rolled so it inherits the navigation bar, the
 * filter sheet, the persistent filter state and the lazy rendering the lists already have; the
 * hand-rolled version had drifted into a different screen with inline dropdowns and no way back.
 *
 * No availability filter: a minifig has no lego.com page, so the concept doesn't apply.
 */
export default function MinifigsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const status = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (q) => (q.state.data?.minifigs.status?.state === 'running' ? 2000 : false),
  })

  const hasCatalog = (status.data?.minifigs.rowCount ?? 0) > 0

  // Everything owned in one fetch; the shared screen then filters and sorts it like any list.
  const { data, isLoading, error } = useQuery({
    queryKey: ['minifigs'],
    queryFn: () =>
      api.get<{ count: number; results: MinifigRow[] }>(
        `/catalog/minifigs${query({ ownedOnly: true, limit: 200 })}`,
      ),
    enabled: hasCatalog,
  })

  const download = useMutation({
    mutationFn: () => api.post('/catalog/minifigs/download'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog-status'] }),
  })

  const downloading = status.data?.minifigs.status?.state === 'running'
  const progress = status.data?.minifigs.status?.progress ?? 0

  /** A minifig wears the `SetRow` shape so the shared screen can filter and sort it unchanged. */
  const rows: SetRow[] = useMemo(
    () =>
      (data?.results ?? []).map((minifig) => ({
        setNum: minifig.figNum,
        name: minifig.name,
        year: minifig.year ?? 0,
        themeId: minifig.themeId ?? 0,
        themeName: minifig.themeName ?? '',
        numParts: minifig.numParts,
        setImgUrl: minifig.imgUrl,
        quantity: minifig.ownedQuantity,
        isInCollection: minifig.ownedQuantity > 0,
        isInWishlist: false,
        hasPriceAlert: false,
        wasScanned: false,
        lastScannedAt: null,
        currentListId: null,
        currentListName: null,
        storePriceEur: minifig.resolvedPrice,
        availability: 'unknown',
        resolvedPrice: minifig.resolvedPrice,
        priceCondition: null,
        priceLabel: null,
      })),
    [data],
  )

  const totalOwned = useMemo(
    () => (data?.results ?? []).reduce((total, row) => total + row.ownedQuantity, 0),
    [data],
  )

  if (!hasCatalog) {
    return (
      <div className="space-y-4">
        <EmptyState
          icon={<Icon name="user" className="h-9 w-9" />}
          title="Catalogue minifigs non téléchargé"
          message="Téléchargez le catalogue Rebrickable (~15 000 minifigs) pour parcourir votre collection. Peut aussi se faire depuis les Paramètres."
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
        {status.data?.minifigs.status?.state === 'error' && (
          <ErrorLabel message={status.data.minifigs.status.message ?? 'Téléchargement échoué'} />
        )}
      </div>
    )
  }

  function toggle(figNum: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(figNum)) next.delete(figNum)
      else next.add(figNum)
      return next
    })
  }

  return (
    <SetListScreen
      title="Mes minifigs"
      screenId="minifigs"
      defaultSort="name"
      // A minifig was never scanned, and never appeared in the sets catalogue snapshot.
      excludedSorts={['dateScanned', 'dateAdded']}
      showAvailabilityFilter={false}
      searchPlaceholder="Nom ou identifiant"
      rows={rows}
      isLoading={isLoading}
      error={error ? (error as Error).message : null}
      bulkActions={[
        {
          key: 'prices',
          label: 'Actualiser les prix',
          run: async (figNums) => {
            const { status: batchStatus } = await api.post<{ status: string }>('/prices/batch/start', {
              setNums: figNums,
            })
            if (batchStatus === 'busy') {
              throw new Error('Une actualisation des prix est déjà en cours — réessayez ensuite.')
            }
          },
        },
      ]}
      header={
        <p className="px-1 text-[13px] text-ink-faint">
          {rows.length} minifig{rows.length > 1 ? 's' : ''} · {totalOwned} exemplaire
          {totalOwned > 1 ? 's' : ''}
        </p>
      }
      renderItems={(visible) => (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {visible.map((row) => (
            <li
              key={row.setNum}
              className={`card space-y-2 ${selected.has(row.setNum) ? 'ring-2 ring-brand' : ''}`}
              onContextMenu={(event) => {
                event.preventDefault()
                toggle(row.setNum)
              }}
            >
              <button
                type="button"
                className="block w-full text-left"
                onClick={() => navigate(`/set/${encodeURIComponent(row.setNum)}`)}
              >
                {/* Fixed box, as on the detail screen: the grid must not reflow as images land. */}
                <div className="flex h-28 items-center justify-center overflow-hidden rounded-lg bg-white">
                  {row.setImgUrl ? (
                    <img
                      src={imageUrl(row.setImgUrl)}
                      alt={row.name}
                      loading="lazy"
                      className="h-full w-full object-contain p-1"
                    />
                  ) : (
                    <Icon name="user" className="h-8 w-8 text-ink-faint" />
                  )}
                </div>
                <div className="mt-2 space-y-0.5">
                  <p className="truncate text-[15px] font-semibold text-ink" title={row.name}>
                    {row.name}
                  </p>
                  <p className="text-[13px] text-ink-faint">
                    {row.setNum}
                    {row.quantity > 1 ? ` · ×${row.quantity}` : ''}
                  </p>
                  {row.resolvedPrice !== null && (
                    <p className="text-[15px] font-bold text-ink">{formatEUR(row.resolvedPrice)}</p>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      emptyState={
        <EmptyState
          icon={<Icon name="user" className="h-9 w-9" />}
          title="Aucune minifig"
          message="Aucun set de votre collection ne contient de minifig répertoriée."
        />
      }
    />
  )
}
