import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, imageUrl } from '../api/client'
import type { CollectionPayload, SetDetail } from '../api/types'
import PriceAlertEditor from '../components/PriceAlertEditor'
import PriceCard from '../components/PriceCard'
import PriceHistoryChart from '../components/PriceHistoryChart'
import ScanPriceEntry from '../components/ScanPriceEntry'
import Icon from '../components/Icon'
import ValuationCard from '../components/ValuationCard'
import { Badge, ConfirmDialog, EmptyState, ErrorLabel, LoadingBlock, Sheet, SetThumbnail } from '../components/ui'
import { useSettings } from '../lib/settings-context'
import {
  CONDITION_LABEL,
  formatDateTime,
  formatEUR,
  formatNumber,
  NON_SET_LABEL,
} from '../lib/format'

interface MinifigEntry {
  setNum: string
  name: string
  quantity: number | null
  setImgUrl: string | null
}

interface RelatedSet {
  setNum: string
  name: string
  numParts: number
  setImgUrl: string | null
}

/**
 * The set sheet.
 *
 * `GET /sets/:setNum` returns everything in one call; live work (a price refresh) is always an
 * explicit action. When the user arrived from a list, that list's set numbers ride along in
 * router state so previous/next can page through it — a snapshot of what was on screen, so
 * removing the current set from the collection doesn't renumber what's under the user's finger.
 */
export default function SetDetailPage() {
  const { setNum = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { preferences } = useSettings()

  const siblings = (location.state as { siblings?: string[] } | null)?.siblings ?? []
  const index = siblings.indexOf(setNum)

  const [showAlertEditor, setShowAlertEditor] = useState(false)
  const [showPaidPrice, setShowPaidPrice] = useState(false)
  const [showScanPrice, setShowScanPrice] = useState(false)
  const [showLists, setShowLists] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [paidPriceValue, setPaidPriceValue] = useState('')

  const key = ['set', setNum]
  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => api.get<SetDetail>(`/sets/${encodeURIComponent(setNum)}`),
  })

  const collection = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
  })

  const minifigs = useQuery({
    queryKey: ['set-minifigs', setNum],
    queryFn: () =>
      api.get<{ count: number; results: MinifigEntry[] }>(`/sets/${encodeURIComponent(setNum)}/minifigs`),
    enabled: Boolean(data) && !data?.isMinifig,
    retry: false,
  })

  const containingSets = useQuery({
    queryKey: ['minifig-sets', setNum],
    queryFn: () =>
      api.get<{ count: number; results: RelatedSet[] }>(`/minifigs/${encodeURIComponent(setNum)}/sets`),
    enabled: Boolean(data) && data?.isMinifig === true,
    retry: false,
  })

  const similar = useQuery({
    queryKey: ['similar', setNum],
    queryFn: () => api.get<{ results: RelatedSet[] }>(`/sets/${encodeURIComponent(setNum)}/similar`),
    enabled: Boolean(data) && !data?.isMinifig,
    retry: false,
  })

  const refresh = useMutation({
    mutationFn: () => api.post(`/prices/${encodeURIComponent(setNum)}/refresh`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  })
  const refreshStore = useMutation({
    mutationFn: () => api.post(`/prices/${encodeURIComponent(setNum)}/store-refresh`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  })
  const setWishlist = useMutation({
    mutationFn: (wanted: boolean) =>
      wanted
        ? api.post(`/wishlist/${encodeURIComponent(setNum)}`)
        : api.delete(`/wishlist/${encodeURIComponent(setNum)}`),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const addToCollection = useMutation({
    mutationFn: (listId: number) => api.post(`/collection/${encodeURIComponent(setNum)}`, { listId }),
    onSuccess: () => {
      setShowLists(false)
      return queryClient.invalidateQueries()
    },
  })
  const removeFromCollection = useMutation({
    mutationFn: () => api.delete(`/collection/${encodeURIComponent(setNum)}`),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const setQuantity = useMutation({
    mutationFn: (quantity: number) => api.patch(`/collection/${encodeURIComponent(setNum)}`, { quantity }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const savePaidPrice = useMutation({
    mutationFn: (value: number | null) =>
      api.put(`/sets/${encodeURIComponent(setNum)}/paid-price`, { paidPriceEur: value }),
    onSuccess: () => {
      setShowPaidPrice(false)
      return queryClient.invalidateQueries({ queryKey: key })
    },
  })

  useEffect(() => {
    setPaidPriceValue(data?.paidPriceEur ? String(data.paidPriceEur) : '')
  }, [data?.paidPriceEur])

  const bestScan = useMemo(
    () => data?.scanEvents.find((event) => event.id === data.bestPriceScanId) ?? null,
    [data],
  )

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorLabel message={(error as Error).message} />
  if (!data) return <EmptyState icon={<Icon name="search" className="h-9 w-9" />} title="Set introuvable" />

  const alertsByCondition = new Map(data.alerts.map((alert) => [alert.condition, alert]))

  return (
    <div className="space-y-5 pb-8">
      <div className="flex items-center justify-between gap-2">
        <button type="button" className="btn-ghost px-2 py-1" onClick={() => navigate(-1)}>
          <Icon name="chevron-left" className="mr-0.5 inline h-4 w-4 align-text-bottom" />
          Retour
        </button>
        {/* Buttons, not only a swipe: a gesture alone is not an affordance, and screen readers
            consume horizontal swipes. */}
        {siblings.length > 1 && index >= 0 && (
          <div className="flex items-center gap-1 text-xs text-ink-faint">
            <button
              type="button"
              className="btn-ghost px-2 py-1"
              disabled={index <= 0}
              onClick={() =>
                navigate(`/set/${encodeURIComponent(siblings[index - 1])}`, { state: { siblings } })
              }
              aria-label="Set précédent"
            >
              <Icon name="chevron-left" className="h-4 w-4" />
            </button>
            <span>
              {index + 1} / {siblings.length}
            </span>
            <button
              type="button"
              className="btn-ghost px-2 py-1"
              disabled={index >= siblings.length - 1}
              onClick={() =>
                navigate(`/set/${encodeURIComponent(siblings[index + 1])}`, { state: { siblings } })
              }
              aria-label="Set suivant"
            >
              <Icon name="chevron-right" className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <section className="card space-y-3">
        {data.set.setImgUrl && (
          <img
            src={imageUrl(data.set.setImgUrl)}
            alt={data.set.name}
            className="mx-auto max-h-56 w-full object-contain"
          />
        )}
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold text-ink">{data.set.setNum}</h1>
            {data.isInWishlist && (
              <Badge tone="brand">
                <Icon name="heart" filled className="h-3 w-3" /> Liste cadeaux
              </Badge>
            )}
            {data.nonSetKind && <Badge tone="warning">{NON_SET_LABEL[data.nonSetKind]}</Badge>}
            {data.isOfflineResult && <Badge tone="neutral">Résultat hors-ligne</Badge>}
          </div>
          <p className="text-base text-ink">{data.set.name}</p>
          <p className="text-sm text-ink-muted">
            {[data.themeName, data.set.year || null, `${formatNumber(data.set.numParts)} pièces`]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {data.isInCollection ? (
            <>
              <Badge tone="positive">
                Dans ma collection{data.currentListName ? ` · ${data.currentListName}` : ''}
              </Badge>
              <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowLists(true)}>
                Changer de liste
              </button>
              <div className="flex items-center gap-1 text-xs">
                <button
                  type="button"
                  className="btn-ghost px-2 py-1"
                  onClick={() => setQuantity.mutate(Math.max(1, data.quantity - 1))}
                  aria-label="Retirer un exemplaire"
                >
                  <Icon name="minus" className="h-4 w-4" />
                </button>
                <span className="min-w-6 text-center font-semibold text-ink">{data.quantity}</span>
                <button
                  type="button"
                  className="btn-ghost px-2 py-1"
                  onClick={() => setQuantity.mutate(data.quantity + 1)}
                  aria-label="Ajouter un exemplaire"
                >
                  <Icon name="plus" className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs text-[rgb(var(--negative))]"
                onClick={() => setConfirmRemove(true)}
              >
                Retirer
              </button>
            </>
          ) : (
            <button type="button" className="btn-primary px-3 py-1.5 text-xs" onClick={() => setShowLists(true)}>
              Ajouter à ma collection
            </button>
          )}
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-xs"
            onClick={() => setWishlist.mutate(!data.isInWishlist)}
          >
            {data.isInWishlist ? 'Retirer des cadeaux' : 'Ajouter aux cadeaux'}
          </button>
          <button
            type="button"
            className="btn-secondary px-3 py-1.5 text-xs"
            onClick={() => setShowScanPrice(true)}
          >
            Prix vu en magasin
          </button>
        </div>
      </section>

      <ValuationCard valuation={data.valuation} onEditPaidPrice={() => setShowPaidPrice(true)} />

      <PriceCard
        detail={data}
        pricePerPartTarget={Number(preferences?.['appTheme.preferredPricePerPart'] ?? 0.12)}
        isRefreshing={refresh.isPending || refreshStore.isPending}
        onRefresh={() => refresh.mutate()}
        onRefreshStore={() => refreshStore.mutate()}
      />

      <PriceHistoryChart history={data.priceHistory} soldListings={data.soldListings} />

      <section className="card space-y-2">
        <h2 className="section-title">Alertes de prix</h2>
        {(['newSet', 'used'] as const).map((condition) => {
          const alert = alertsByCondition.get(condition)
          return (
            <div key={condition} className="flex items-center justify-between gap-3 py-1">
              <span className="text-sm text-ink">
                {CONDITION_LABEL[condition]}
                {alert && (
                  <span className="block text-xs text-ink-faint">
                    Seuil {formatEUR(alert.effectiveThresholdEur)}
                    {alert.isEnabled ? '' : ' · désactivée'}
                  </span>
                )}
              </span>
              <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowAlertEditor(true)}>
                {alert ? 'Modifier' : 'Créer'}
              </button>
            </div>
          )
        })}
      </section>

      {data.scanEvents.length > 0 && (
        <section className="card space-y-2">
          <h2 className="section-title">Historique des scans</h2>
          <ul className="divide-y divide-line">
            {data.scanEvents.map((event) => (
              <li key={event.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block text-ink">{formatDateTime(event.scannedAt)}</span>
                  {event.placeName && <span className="block text-xs text-ink-faint">{event.placeName}</span>}
                </span>
                {event.priceSeenEur !== null && (
                  <span className="shrink-0 text-right">
                    <span className="font-semibold text-ink">{formatEUR(event.priceSeenEur)}</span>
                    {bestScan?.id === event.id && (
                      <span className="block text-xs text-[rgb(var(--positive))]">meilleur prix vu</span>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {!data.isMinifig && (minifigs.data?.results.length ?? 0) > 0 && (
        <Gallery
          title="Minifigs de ce set"
          items={(minifigs.data?.results ?? []).map((entry) => ({
            key: entry.setNum,
            name: entry.name,
            imgUrl: entry.setImgUrl,
            caption: entry.quantity && entry.quantity > 1 ? `×${entry.quantity}` : entry.setNum,
          }))}
          onOpen={(figNum) => navigate(`/set/${encodeURIComponent(figNum)}`)}
        />
      )}

      {data.isMinifig && (containingSets.data?.results.length ?? 0) > 0 && (
        <Gallery
          title="Sets contenant cette minifig"
          items={(containingSets.data?.results ?? []).map((entry) => ({
            key: entry.setNum,
            name: entry.name,
            imgUrl: entry.setImgUrl,
            caption: entry.setNum,
          }))}
          onOpen={(target) => navigate(`/set/${encodeURIComponent(target)}`)}
        />
      )}

      {!data.isMinifig && (similar.data?.results.length ?? 0) > 0 && (
        <Gallery
          title="Sets similaires"
          items={(similar.data?.results ?? []).slice(0, 12).map((entry) => ({
            key: entry.setNum,
            name: entry.name,
            imgUrl: entry.setImgUrl,
            caption: `${formatNumber(entry.numParts)} pièces`,
          }))}
          onOpen={(target) => navigate(`/set/${encodeURIComponent(target)}`)}
        />
      )}

      <Sheet open={showLists} title="Choisir une liste" onClose={() => setShowLists(false)}>
        <div className="space-y-2">
          {(collection.data?.lists ?? []).map((list) => (
            <button
              key={list.id}
              type="button"
              className="btn-secondary w-full"
              onClick={() => addToCollection.mutate(list.id)}
            >
              {list.name} · {CONDITION_LABEL[list.condition]}
            </button>
          ))}
          {!collection.data?.lists.length && (
            <p className="text-sm text-ink-muted">
              Aucune liste Rebrickable. Synchronise ta collection ou crée une liste sur rebrickable.com.
            </p>
          )}
        </div>
      </Sheet>

      <Sheet open={showPaidPrice} title="Prix payé" onClose={() => setShowPaidPrice(false)}>
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Le prix que tu as réellement payé sert de référence à l'évolution. Il est conservé même
            si tu vides le cache.
          </p>
          <input
            className="input"
            type="number"
            step="0.01"
            min="0"
            value={paidPriceValue}
            onChange={(event) => setPaidPriceValue(event.target.value)}
          />
          <button
            type="button"
            className="btn-primary w-full"
            onClick={() => savePaidPrice.mutate(paidPriceValue ? Number(paidPriceValue) : null)}
          >
            Enregistrer
          </button>
        </div>
      </Sheet>

      <ScanPriceEntry
        open={showScanPrice}
        onClose={() => setShowScanPrice(false)}
        setNum={setNum}
        onSaved={() => queryClient.invalidateQueries({ queryKey: key })}
      />

      <PriceAlertEditor
        open={showAlertEditor}
        onClose={() => setShowAlertEditor(false)}
        setNum={setNum}
        setName={data.set.name}
        existing={data.alerts[0] ?? null}
        referenceHint={
          data.storePriceEur
            ? { amount: data.storePriceEur, sourceName: 'lego.com (officiel)' }
            : data.valuation.currentValueEur
              ? { amount: data.valuation.currentValueEur, sourceName: 'valeur estimée' }
              : null
        }
      />

      <ConfirmDialog
        open={confirmRemove}
        title="Retirer de la collection"
        message="Le set sera retiré de ta collection Rebrickable. Les scans, le prix payé et les alertes sont conservés."
        confirmLabel="Retirer"
        destructive
        onConfirm={() => {
          removeFromCollection.mutate()
          setConfirmRemove(false)
        }}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  )
}

function Gallery({
  title,
  items,
  onOpen,
}: {
  title: string
  items: { key: string; name: string; imgUrl: string | null; caption: string }[]
  onOpen: (key: string) => void
}) {
  return (
    <section className="card space-y-2">
      <h2 className="section-title">{title}</h2>
      <ul className="flex gap-3 overflow-x-auto pb-1">
        {items.map((item) => (
          <li key={item.key} className="w-24 shrink-0">
            <button type="button" className="w-full text-left" onClick={() => onOpen(item.key)}>
              <SetThumbnail url={item.imgUrl} alt={item.name} size="lg" />
              <span className="mt-1 block truncate text-xs font-medium text-ink" title={item.name}>
                {item.name}
              </span>
              <span className="block truncate text-[11px] text-ink-faint">{item.caption}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
