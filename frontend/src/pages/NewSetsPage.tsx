import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, query } from '../api/client'
import type { CatalogStatus, SetRow, StoreAvailability } from '../api/types'
import Icon from '../components/Icon'
import ListPickerSheet from '../components/ListPickerSheet'
import SetListScreen from '../components/SetListScreen'
import { EmptyState, ErrorLabel, Spinner } from '../components/ui'
import { useSetActions } from '../hooks/useSetActions'
import { useFilterState } from '../hooks/useFilterState'
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
  availability: StoreAvailability
  resolvedPrice: number | null
}

const PAGE_SIZE = 60

/**
 * The catalogue browser.
 *
 * Two things make this screen different from the other lists, and both are server-side:
 * it shows only entries that appeared *after* the first catalogue import (otherwise "new" would
 * mean all 28 000 rows), and it filters/sorts on the server — filtering one 60-row page client-side
 * made searching a set that wasn't on that page report "no results".
 */
export default function NewSetsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const actions = useSetActions()
  const [page, setPage] = useState(0)
  const [includeAll, setIncludeAll] = useState(false)

  // Two distinct screen ids, not one: "nouveautés" defaults to `dateAdded` (what just appeared is
  // the point), but that same field means "when this install happened to see the entry in a
  // snapshot" while browsing the full ~28 000-row catalogue, where `year` is what's actually
  // useful. `useFilterState`'s store keys purely on screen id and locks in whichever `defaultSort`
  // its first call passed — a single id couldn't hold two defaults.
  const screenId = includeAll ? 'new-sets-catalog' : 'new-sets'
  const defaultSort = includeAll ? 'year' : 'dateAdded'

  // The shared filter state drives the *request* here rather than a client-side pass.
  const { filter } = useFilterState(screenId, defaultSort)

  useEffect(() => {
    setPage(0)
  }, [filter.search, filter.themeName, filter.year, filter.ownedOnly, filter.availability, filter.sort, filter.ascending, includeAll])

  const status = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (q) => (q.state.data?.sets.status?.state === 'running' ? 2000 : false),
  })

  const hasCatalog = (status.data?.sets.rowCount ?? 0) > 0

  const { data, isLoading, error } = useQuery({
    queryKey: ['new-sets', page, includeAll, filter],
    queryFn: () =>
      api.get<{ count: number; results: CatalogSetRow[]; isFiltered: boolean }>(
        `/catalog/new-sets${query({
          search: filter.search,
          themeName: filter.themeName,
          year: filter.year,
          ownedOnly: filter.ownedOnly === null ? null : String(filter.ownedOnly),
          availability: filter.availability,
          sort: filter.sort,
          ascending: filter.ascending,
          includeAll,
          offset: page * PAGE_SIZE,
          limit: PAGE_SIZE,
        })}`,
      ),
    enabled: hasCatalog,
  })

  // Over the whole catalogue this screen browses, not just the current 60-row page — a dropdown
  // built from `rows` alone offered only what happened to be on that page (#finding-10).
  const filterOptions = useQuery({
    queryKey: ['new-sets-filter-options', includeAll],
    queryFn: () =>
      api.get<{ themes: string[]; years: number[] }>(
        `/catalog/new-sets/filter-options${query({ includeAll })}`,
      ),
    enabled: hasCatalog,
    staleTime: 5 * 60 * 1000,
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

  // Shaped for the shared list screen, which speaks `SetRow`.
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
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1)

  return (
    <>
      <SetListScreen
        title="Nouveaux sets"
        screenId={screenId}
        defaultSort={defaultSort}
        // A catalogue entry was never scanned, so that sort would mean nothing here.
        excludedSorts={['dateScanned']}
        showOwnedFilter
        // The rows are already the server's answer; filtering them again would re-filter one page.
        serverFiltered
        rows={rows}
        themeOptions={filterOptions.data?.themes}
        yearOptions={filterOptions.data?.years}
        isLoading={isLoading}
        error={error ? (error as Error).message : null}
        bulkActions={[actions.refreshPrices, actions.addToCollection, actions.addToWishlist]}
        onRefresh={() => download.mutate()}
        isRefreshing={downloading}
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
        emptyState={
          <EmptyState
            icon={<Icon name="sparkles" className="h-9 w-9" />}
            title="Aucun nouveau set pour l'instant"
            message="Les sets ajoutés au catalogue Rebrickable depuis votre dernière synchronisation apparaîtront ici."
            action={
              <button type="button" className="btn-secondary" onClick={() => setIncludeAll(true)}>
                Parcourir tout le catalogue
              </button>
            }
          />
        }
        header={
          <div className="flex flex-wrap items-center gap-2 px-1 text-[13px] text-ink-faint">
            <span>
              {total} set{total > 1 ? 's' : ''}
              {data?.isFiltered ? ' depuis la première synchronisation' : ' au catalogue'}
            </span>
            <button
              type="button"
              className="btn-ghost px-1 py-0 text-[13px]"
              onClick={() => setIncludeAll((value) => !value)}
            >
              {includeAll ? 'Nouveautés seulement' : 'Tout le catalogue'}
            </button>
            {total > PAGE_SIZE && (
              <span className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  className="btn-ghost px-1 py-0 text-[13px]"
                  onClick={() => setPage((value) => Math.max(0, value - 1))}
                  disabled={page === 0}
                >
                  ‹
                </button>
                {page + 1} / {lastPage + 1}
                <button
                  type="button"
                  className="btn-ghost px-1 py-0 text-[13px]"
                  onClick={() => setPage((value) => Math.min(lastPage, value + 1))}
                  disabled={page >= lastPage}
                >
                  ›
                </button>
              </span>
            )}
          </div>
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
