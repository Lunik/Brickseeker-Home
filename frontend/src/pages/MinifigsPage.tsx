import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, imageUrl, query } from '../api/client'
import type { CatalogStatus, MinifigRow, SetRow } from '../api/types'
import Icon from '../components/Icon'
import SetListScreen from '../components/SetListScreen'
import { useFilterState } from '../hooks/useFilterState'
import { EmptyState, ErrorLabel, Spinner } from '../components/ui'
import { formatEUR } from '../lib/format'

/** How many rows one request may bring back, per mode. */
const OWNED_LIMIT = 5000
const BROWSE_LIMIT = 300

/**
 * Survives leaving the gallery, as the iOS filter singleton does — coming back to a screen that
 * silently forgot you were browsing the whole catalogue is the same annoyance as a reset filter.
 */
let ownedOnlyPreference = true

/**
 * The minifig gallery — the same browse screen as the lists, with a grid of cards instead of rows.
 * Built on `SetListScreen` rather than hand-rolled so it inherits the navigation bar, the filter
 * sheet, the persistent filter state and the lazy rendering the lists already have.
 *
 * Filtering and sorting happen **server-side**, unlike the collection screens: the catalogue holds
 * ~17 000 minifigs and shipping it to filter in the browser is not a trade worth making. That is
 * also why the screen reads `count` — the total *before* slicing — rather than counting the rows it
 * received: asking for 200 and printing "200 minifigs" is how this screen came to claim 200 while
 * Accueil, reading the same endpoint, said 601.
 *
 * No availability filter: a minifig has no lego.com page, so the concept doesn't apply.
 */
export default function MinifigsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [ownedOnly, setOwnedOnlyState] = useState(ownedOnlyPreference)
  // The same store instance `SetListScreen` uses for this screen id, so the search field and the
  // filter sheet drive the query without a second copy of that state.
  const { filter } = useFilterState('minifigs', 'name')

  function setOwnedOnly(value: boolean) {
    ownedOnlyPreference = value
    setOwnedOnlyState(value)
  }

  const status = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (q) => (q.state.data?.minifigs.status?.state === 'running' ? 2000 : false),
  })

  const hasCatalog = (status.data?.minifigs.rowCount ?? 0) > 0

  const { data, isLoading, error } = useQuery({
    queryKey: ['minifigs', ownedOnly, filter],
    queryFn: () =>
      api.get<{ count: number; results: MinifigRow[] }>(
        `/catalog/minifigs${query({
          search: filter.search,
          themeName: filter.themeName,
          year: filter.year,
          ownedOnly,
          sort: filter.sort,
          ascending: filter.ascending,
          // Owned: the whole set, so the count on screen is the collection, not a page of it.
          // Browsing: a page, because the alternative is 17 000 rows over the wire.
          limit: ownedOnly ? OWNED_LIMIT : BROWSE_LIMIT,
        })}`,
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

  /** `count` is the whole result; `rows` is what arrived. They differ only when a page was cut. */
  const total = data?.count ?? 0
  const truncated = total > rows.length

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
      // The server did the filtering and the sorting; re-applying them here would only re-filter
      // a page that is already a subset, and hide rows the server deliberately matched.
      serverFiltered
      isLoading={isLoading}
      error={error ? (error as Error).message : null}
      navActions={
        // The iOS `shippingbox` toolbar toggle: "Possédées seulement". Off, the screen browses the
        // whole Rebrickable catalogue.
        <button
          type="button"
          // Tinted rather than filled: this icon set is line art, and filling the box glyph turns
          // it into a solid blob.
          className={`nav-circle ${ownedOnly ? 'bg-brand text-white' : 'text-ink-muted'}`}
          onClick={() => setOwnedOnly(!ownedOnly)}
          aria-pressed={ownedOnly}
          aria-label="Possédées seulement"
          title="Possédées seulement"
        >
          <Icon name="box" />
        </button>
      }
      bulkActions={[
        {
          key: 'prices',
          label: 'Actualiser les prix',
          icon: 'refresh',
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
        <div className="px-1 text-[13px] text-ink-faint">
          <p>
            {total} minifig{total > 1 ? 's' : ''}
            {ownedOnly && !truncated && (
              <>
                {' '}
                · {totalOwned} exemplaire{totalOwned > 1 ? 's' : ''}
              </>
            )}
            {!ownedOnly && ' du catalogue'}
          </p>
          {/* Never let a cut page pass for the whole answer. */}
          {truncated && (
            <p>
              {rows.length} affichée{rows.length > 1 ? 's' : ''} — affinez la recherche ou les
              filtres pour voir les autres.
            </p>
          )}
        </div>
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
                {/* Fixed box, as on the detail screen: the grid must not reflow as images land.
                    Desaturated when the minifig isn't owned — while browsing the whole catalogue
                    that is the only thing telling "mine" from "exists", as on iOS. */}
                <div
                  className={`flex h-28 items-center justify-center overflow-hidden rounded-lg bg-white ${
                    row.isInCollection ? '' : 'opacity-60 grayscale'
                  }`}
                >
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
