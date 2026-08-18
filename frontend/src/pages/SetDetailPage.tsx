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
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorLabel,
  LoadingBlock,
  MinifigPlaceholder,
  Sheet,
  SetThumbnail,
  StatusLine,
} from '../components/ui'
import { useSettings } from '../lib/settings-context'
import {
  baseSetNum,
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

  const navState = location.state as { siblings?: string[]; scanEventId?: number | null } | null
  const siblings = navState?.siblings ?? []
  const index = siblings.indexOf(setNum)

  const [alertCondition, setAlertCondition] = useState<'newSet' | 'used' | null>(null)
  const [showPaidPrice, setShowPaidPrice] = useState(false)
  const [showScanPrice, setShowScanPrice] = useState(false)
  const [showLists, setShowLists] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [paidPriceValue, setPaidPriceValue] = useState('')
  // Paging through siblings reuses this component (the route has no `key`), so a broken image on
  // one set must not keep showing the placeholder once the pager moves to a set whose image is fine.
  const [heroImageFailed, setHeroImageFailed] = useState(false)
  useEffect(() => setHeroImageFailed(false), [setNum])

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
  const setWishlist = useMutation({
    mutationFn: (wanted: boolean) =>
      wanted
        ? api.post(`/wishlist/${encodeURIComponent(setNum)}`)
        : api.delete(`/wishlist/${encodeURIComponent(setNum)}`),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const addToCollection = useMutation({
    // Adding and moving are different endpoints: POST only adds, so using it on a set already in
    // a list left the set in both. PATCH performs the delete-then-add Rebrickable requires.
    mutationFn: (listId: number) =>
      data?.isInCollection
        ? api.patch(`/collection/${encodeURIComponent(setNum)}`, { listId })
        : api.post(`/collection/${encodeURIComponent(setNum)}`, { listId }),
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
  const deleteScan = useMutation({
    mutationFn: (eventId: number) => api.delete(`/history/events/${eventId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
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

  const armedAlerts = data.alerts.filter((alert) => alert.isEnabled)
  /** Three states, as on iOS: no alert, a stored alert switched off, and one actually armed. */
  const alertSummary = armedAlerts.length
    ? armedAlerts
        .map(
          (alert) =>
            `${CONDITION_LABEL[alert.condition].toLowerCase()} sous ${formatEUR(alert.effectiveThresholdEur)}`,
        )
        .join(' · ')
    : data.alerts.length
      ? 'Désactivée'
      : null

  return (
    <div className="space-y-5 pb-8">
      {/* The pager header, matching the iOS sheet: chevrons grouped in one pill on the left, the
          position centred, "Fermer" on the right. */}
      <div className="sticky top-0 z-30 -mx-4 flex items-center gap-2 bg-surface/90 px-4 py-2 backdrop-blur">
        {siblings.length > 1 && index >= 0 ? (
          <div className="flex items-center rounded-full bg-surface-raised">
            <button
              type="button"
              className="flex h-11 w-12 items-center justify-center text-brand disabled:opacity-30"
              disabled={index <= 0}
              onClick={() =>
                // `replace`: paging is movement *inside* one screen, as it is in the iOS pager, not
                // a stack of screens. Pushing left a trail — after three taps on "suivant",
                // "Fermer" walked back through the three sets instead of returning to the list.
                navigate(`/set/${encodeURIComponent(siblings[index - 1])}`, {
                  state: { siblings },
                  replace: true,
                })
              }
              aria-label="Set précédent"
            >
              <Icon name="chevron-left" className="h-6 w-6" />
            </button>
            <button
              type="button"
              className="flex h-11 w-12 items-center justify-center text-brand disabled:opacity-30"
              disabled={index >= siblings.length - 1}
              onClick={() =>
                navigate(`/set/${encodeURIComponent(siblings[index + 1])}`, {
                  state: { siblings },
                  replace: true,
                })
              }
              aria-label="Set suivant"
            >
              <Icon name="chevron-right" className="h-6 w-6" />
            </button>
          </div>
        ) : (
          <span className="w-24" />
        )}
        <span className="min-w-0 flex-1 truncate text-center text-[17px] font-semibold text-ink">
          {siblings.length > 1 && index >= 0 ? `${index + 1} sur ${siblings.length}` : ''}
        </span>
        <button type="button" className="nav-pill" onClick={() => navigate(-1)}>
          Fermer
        </button>
      </div>

      <section className="space-y-3">
        {/* A fixed box reserved before the image loads: without it the whole page shifted down
            the moment the artwork arrived, moving whatever the user was about to tap. */}
        <div className="flex h-64 w-full items-center justify-center overflow-hidden rounded-2xl bg-white/5">
          {data.set.setImgUrl && !heroImageFailed ? (
            <img
              src={imageUrl(data.set.setImgUrl)}
              alt={data.set.name}
              className="h-full w-full object-contain"
              onError={() => setHeroImageFailed(true)}
            />
          ) : data.isMinifig ? (
            // The tile itself is `bg-white/5` (near-transparent, dark in dark mode) — safe only
            // because the placeholder's own background is transparent (#finding-15), not white.
            <MinifigPlaceholder className="h-40 w-40" />
          ) : (
            <Icon name="brick" className="h-12 w-12 text-ink-faint" />
          )}
        </div>

        <div className="space-y-1 text-center">
          <h1 className="text-[34px] font-bold leading-tight text-ink">{baseSetNum(data.set.setNum)}</h1>
          <p className="text-[22px] leading-tight text-ink">{data.set.name}</p>
          <p className="text-[17px] text-ink-muted">
            {[data.set.year || null, `${formatNumber(data.set.numParts)} pièces`].filter(Boolean).join(' · ')}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            {data.nonSetKind && <Badge tone="warning">{NON_SET_LABEL[data.nonSetKind]}</Badge>}
            {data.isOfflineResult && <Badge tone="neutral">Résultat hors-ligne</Badge>}
          </div>
        </div>

        {data.isInCollection ? (
          <StatusLine>
            Dans votre liste «&nbsp;{data.currentListName ?? 'collection'}&nbsp;»
          </StatusLine>
        ) : (
          <StatusLine tone="neutral">Pas dans votre collection</StatusLine>
        )}

        {data.isInCollection && (
          <div className="flex items-center justify-between gap-3 pt-1">
            <span className="text-[20px] text-ink">Quantité : ×{data.quantity}</span>
            <div className="flex items-center rounded-xl bg-surface-raised">
              <button
                type="button"
                className="flex h-11 w-12 items-center justify-center text-ink disabled:opacity-30"
                onClick={() => setQuantity.mutate(Math.max(1, data.quantity - 1))}
                disabled={data.quantity <= 1}
                aria-label="Retirer un exemplaire"
              >
                <Icon name="minus" className="h-5 w-5" />
              </button>
              <span className="h-6 w-px bg-line" />
              <button
                type="button"
                className="flex h-11 w-12 items-center justify-center text-ink"
                onClick={() => setQuantity.mutate(data.quantity + 1)}
                aria-label="Ajouter un exemplaire"
              >
                <Icon name="plus" className="h-5 w-5" />
              </button>
            </div>
          </div>
        )}

        {/* Grouped by what they act on: the two that change where the set lives, then the two
            that watch its price. Five identical full-width rows gave equal weight to everything. */}
        <div className="space-y-3 pt-1">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              className={data.isInCollection ? 'btn-secondary' : 'btn-primary'}
              onClick={() => setShowLists(true)}
            >
              <Icon name="box" className="h-5 w-5" />
              {data.isInCollection ? 'Changer de liste' : 'Ajouter'}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setWishlist.mutate(!data.isInWishlist)}
            >
              <Icon name="heart" filled={data.isInWishlist} className="h-5 w-5" />
              {data.isInWishlist ? 'Retirer' : 'Cadeaux'}
            </button>
          </div>

          <div className="list-card">
            {/* One row for both conditions, carrying their state — as on iOS, where the same row
                is the "an alert is armed" marker. A second card at the foot of the screen listing
                "Neuf / Occasion · Créer" said the same thing twice. */}
            <button
              type="button"
              className="flex w-full items-center gap-3 border-b border-line px-4 py-3 text-left active:bg-surface-sunken"
              onClick={() => setAlertCondition(data.alerts[0]?.condition ?? 'newSet')}
            >
              <Icon
                name={armedAlerts.length ? 'bell' : data.alerts.length ? 'bell-off' : 'bell'}
                filled={armedAlerts.length > 0}
                className={`h-5 w-5 ${armedAlerts.length ? 'text-[rgb(var(--warning))]' : 'text-brand'}`}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-[17px] text-ink">Alerte de prix</span>
                {alertSummary && (
                  <span className="block text-[13px] text-ink-faint">{alertSummary}</span>
                )}
              </span>
              <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-ink-faint" />
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-sunken"
              onClick={() => setShowScanPrice(true)}
            >
              <Icon name="tag" className="h-5 w-5 text-brand" />
              <span className="flex-1 text-[17px] text-ink">Prix vu en magasin</span>
              <Icon name="chevron-right" className="h-4 w-4 text-ink-faint" />
            </button>
          </div>

          {data.isInCollection && (
            <button
              type="button"
              className="btn-ghost w-full text-[rgb(var(--negative))]"
              onClick={() => setConfirmRemove(true)}
            >
              Retirer de ma collection
            </button>
          )}
        </div>
      </section>

      <ValuationCard valuation={data.valuation} onEditPaidPrice={() => setShowPaidPrice(true)} />

      <PriceCard
        detail={data}
        pricePerPartTarget={Number(preferences?.['appTheme.preferredPricePerPart'] ?? 0.12)}
        isRefreshing={refresh.isPending}
        onRefresh={() => refresh.mutate()}
      />

      <PriceHistoryChart history={data.priceHistory} soldListings={data.soldListings} />

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
                <span className="flex shrink-0 items-center gap-2">
                  {event.priceSeenEur !== null && (
                    <span className="text-right">
                      <span className="font-semibold text-ink">{formatEUR(event.priceSeenEur)}</span>
                      {bestScan?.id === event.id && (
                        <span className="block text-[11px] text-[rgb(var(--positive))]">meilleur prix vu</span>
                      )}
                    </span>
                  )}
                  <button
                    type="button"
                    className="px-1 text-[rgb(var(--negative))]"
                    onClick={() => deleteScan.mutate(event.id)}
                    aria-label="Supprimer ce scan"
                  >
                    <Icon name="close" className="h-4 w-4" />
                  </button>
                </span>
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
          isMinifig
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

      {/* Last on the page, as on iOS: everything here leaves the app, so nothing that belongs to
          the set should sit underneath it. Left-aligned like every other row in the app —
          centred links read as a call to action, and these are a footer. */}
      <section className="card space-y-1">
        <h2 className="section-title">Liens</h2>
        {data.set.setUrl && (
          <a
            className="btn-ghost w-full justify-start px-0 text-left"
            href={data.set.setUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Voir sur Rebrickable
          </a>
        )}
        {data.storeUrl && (
          <a
            className="btn-ghost w-full justify-start px-0 text-left"
            href={data.storeUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Voir sur lego.com
          </a>
        )}
        {data.instructionsUrl && (
          <a
            className="btn-ghost w-full justify-start px-0 text-left"
            href={data.instructionsUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Notice de montage
          </a>
        )}
      </section>

      <Sheet open={showLists} title="Choisir une liste" onClose={() => setShowLists(false)}>
        <div className="space-y-2">
          {(collection.data?.lists ?? [])
            .filter((list) => list.id !== data.currentListId)
            .map((list) => (
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
              Aucune liste Rebrickable. Synchronisez votre collection ou créez une liste sur rebrickable.com.
            </p>
          )}
        </div>
      </Sheet>

      <Sheet open={showPaidPrice} title="Prix payé" onClose={() => setShowPaidPrice(false)}>
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Le prix que vous avez réellement payé sert de référence à l'évolution. Il est conservé même
            si vous videz le cache.
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
        // Patches the scan the lookup just recorded rather than creating a second one.
        scanEventId={navState?.scanEventId ?? null}
        onSaved={() => queryClient.invalidateQueries({ queryKey: key })}
      />

      <PriceAlertEditor
        // Keyed on the condition so the editor remounts with that condition's own alert — without
        // it, opening "occasion" showed the "neuf" threshold and saving wrote it to the wrong one.
        key={alertCondition ?? 'none'}
        open={alertCondition !== null}
        onClose={() => setAlertCondition(null)}
        setNum={setNum}
        setName={data.set.name}
        condition={alertCondition ?? 'newSet'}
        alerts={data.alerts}
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
        message="Le set sera retiré de votre collection Rebrickable. Les scans, le prix payé et les alertes sont conservés."
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
  isMinifig = false,
}: {
  title: string
  items: { key: string; name: string; imgUrl: string | null; caption: string }[]
  onOpen: (key: string) => void
  /** Whether every item here is a minifig — "Minifigs de ce set" is, "Sets similaires" isn't. */
  isMinifig?: boolean
}) {
  return (
    <section className="card space-y-2">
      <h2 className="section-title">{title}</h2>
      <ul className="flex gap-3 overflow-x-auto pb-1">
        {items.map((item) => (
          <li key={item.key} className="w-24 shrink-0">
            <button type="button" className="w-full text-left" onClick={() => onOpen(item.key)}>
              <SetThumbnail url={item.imgUrl} alt={item.name} size="lg" isMinifig={isMinifig} />
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
