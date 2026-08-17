import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, imageUrl, query } from '../api/client'
import type { CatalogStatus, MinifigRow } from '../api/types'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, LoadingBlock, NavBar, Spinner } from '../components/ui'
import { formatEUR } from '../lib/format'

/**
 * The owned-minifig gallery: the same browse screen as the lists, but a grid of cards.
 *
 * No availability filter here, deliberately — a minifig has no lego.com page, so the concept
 * doesn't apply to it.
 */
export default function MinifigsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('name')
  const [ownedOnly, setOwnedOnly] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const status = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (q) => (q.state.data?.minifigs.status?.state === 'running' ? 2000 : false),
  })

  const hasCatalog = (status.data?.minifigs.rowCount ?? 0) > 0

  const { data, isLoading, error } = useQuery({
    queryKey: ['minifigs', search, sort, ownedOnly],
    queryFn: () =>
      api.get<{ count: number; results: MinifigRow[] }>(
        `/catalog/minifigs${query({ search, sort, ownedOnly, limit: 200 })}`,
      ),
    enabled: hasCatalog,
  })

  const download = useMutation({
    mutationFn: () => api.post('/catalog/minifigs/download'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog-status'] }),
  })

  const downloading = status.data?.minifigs.status?.state === 'running'
  const progress = status.data?.minifigs.status?.progress ?? 0

  const totalOwned = useMemo(
    () => (data?.results ?? []).reduce((total, row) => total + row.ownedQuantity, 0),
    [data],
  )

  if (!hasCatalog) {
    return (
      <div className="space-y-4">
        <NavBar title="Mes minifigs" />
        <EmptyState
          icon={<Icon name="user" className="h-9 w-9" />}
          title="Catalogue des minifigs non téléchargé"
          message="La galerie croise le catalogue Rebrickable avec votre collection pour savoir quelles minifigs vous possédez. Le téléchargement se fait une fois, puis tout est local."
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

  return (
    <div className="space-y-3">
      <NavBar
        title="Mes minifigs"
        actions={<span className="px-1 text-[13px] text-ink-faint">{totalOwned} ex.</span>}
      />

      <div className="flex gap-2">
        <input
          type="search"
          className="input flex-1"
          placeholder="Nom ou identifiant"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Rechercher"
        />
        <select
          className="input w-auto"
          value={sort}
          onChange={(event) => setSort(event.target.value)}
          aria-label="Trier"
        >
          <option value="name">Nom</option>
          <option value="year">Année</option>
          <option value="partCount">Pièces</option>
          <option value="price">Prix</option>
        </select>
      </div>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-[15px] text-ink">
          <input
            type="checkbox"
            checked={ownedOnly}
            onChange={(event) => setOwnedOnly(event.target.checked)}
          />
          Possédées seulement
        </label>
        {selected.size > 0 && (
          <button
            type="button"
            className="btn-ghost ml-auto px-2 py-1 text-[13px]"
            onClick={async () => {
              await api.post('/prices/batch/start', { setNums: [...selected] })
              setSelected(new Set())
            }}
          >
            Actualiser les prix ({selected.size})
          </button>
        )}
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : error ? (
        <ErrorLabel message={(error as Error).message} />
      ) : !data?.results.length ? (
        <EmptyState
          icon={<Icon name="user" className="h-9 w-9" />}
          title="Aucune minifig"
          message="Aucune minifig ne correspond, ou aucun set de votre collection n'en contient."
        />
      ) : (
        <>
          <p className="text-xs text-ink-faint">{data.count} minifig(s)</p>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {data.results.map((minifig) => (
              <li
                key={minifig.figNum}
                className={`card space-y-2 ${selected.has(minifig.figNum) ? 'ring-2 ring-brand' : ''}`}
                onContextMenu={(event) => {
                  event.preventDefault()
                  setSelected((current) => {
                    const next = new Set(current)
                    if (next.has(minifig.figNum)) next.delete(minifig.figNum)
                    else next.add(minifig.figNum)
                    return next
                  })
                }}
              >
                <button
                  type="button"
                  className="block w-full text-left"
                  onClick={() => navigate(`/set/${encodeURIComponent(minifig.figNum)}`)}
                >
                <div className="flex h-28 items-center justify-center rounded-lg bg-surface-sunken">
                  {minifig.imgUrl ? (
                    <img
                      src={imageUrl(minifig.imgUrl)}
                      alt={minifig.name}
                      loading="lazy"
                      className="h-full w-full object-contain p-1"
                    />
                  ) : (
                    <Icon name="user" className="h-8 w-8 text-ink-faint" />
                  )}
                </div>
                <div className="space-y-0.5">
                  <p className="truncate text-sm font-semibold text-ink" title={minifig.name}>
                    {minifig.name}
                  </p>
                  <p className="text-xs text-ink-faint">
                    {minifig.figNum}
                    {minifig.ownedQuantity > 1 ? ` · ×${minifig.ownedQuantity}` : ''}
                  </p>
                  {minifig.resolvedPrice !== null && (
                    <p className="text-sm font-bold text-ink">{formatEUR(minifig.resolvedPrice)}</p>
                  )}
                </div>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
