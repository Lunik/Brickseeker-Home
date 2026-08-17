import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BatchStatus, SetPrices } from '../api/types'
import Icon from '../components/Icon'
import ListPickerSheet from '../components/ListPickerSheet'
import { ConfirmDialog, EmptyState, ErrorLabel, NavBar, SetThumbnail, Spinner } from '../components/ui'
import { useSetActions } from '../hooks/useSetActions'
import { batchSession, useBatchSession } from '../lib/batch-session'
import { bestDeal } from '../lib/deal'
import { baseSetNum, formatEUR, SOURCE_LABEL } from '../lib/format'

/**
 * The end of a "mode lot" sweep: everything scanned this session, best deal first — the port of
 * iOS `BatchSessionSummaryView`.
 *
 * A **route**, not a sheet. The point of the screen is to open a set and come back, and a sheet
 * over the scanner could not survive that: opening a set unmounts the scanner. As a route it also
 * means the browser's own back button does the right thing from the set sheet.
 *
 * The session's prices are fetched by the server's own serial updater rather than a fan-out from
 * here: each set costs a headless browser page per source, and the updater is the one place that
 * queues that work — which also means it can be busy with somebody else's run, and the notice line
 * says so rather than leaving the rows blank with no explanation.
 */
export default function BatchSessionPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const items = useBatchSession()
  const actions = useSetActions()

  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [startStatus, setStartStatus] = useState<string | null>(null)

  // One cheap read per set: these are pure DB lookups, no scraping, so N in parallel is fine.
  const priceQueries = useQueries({
    queries: items.map((item) => ({
      queryKey: ['prices', item.setNum],
      queryFn: () => api.get<SetPrices>(`/prices/${encodeURIComponent(item.setNum)}`),
      staleTime: 30_000,
    })),
  })

  const batch = useQuery({
    queryKey: ['priceBatch'],
    queryFn: () => api.get<BatchStatus>('/prices/batch/status'),
    refetchInterval: (query) => (query.state.data?.isRunning ? 2000 : false),
  })

  const prices = useMemo(() => {
    const map = new Map<string, SetPrices>()
    items.forEach((item, index) => {
      const data = priceQueries[index]?.data
      if (data) map.set(item.setNum, data)
    })
    return map
  }, [items, priceQueries])

  /** A set with neither a retail price nor a single quote has never been priced. */
  const missing = useMemo(
    () =>
      items
        .filter((item) => {
          const entry = prices.get(item.setNum)
          return entry !== undefined && entry.storePriceEur === null && entry.quotes.length === 0
        })
        .map((item) => item.setNum),
    [items, prices],
  )

  const allLoaded = priceQueries.length > 0 && priceQueries.every((query) => query.isSuccess)
  const signature = items.map((item) => item.setNum).join(',')

  const startPricing = useMutation({
    mutationFn: async (setNums: string[]) => {
      const { status } = await api.post<{ status: string }>('/prices/batch/start', { setNums })
      await queryClient.invalidateQueries({ queryKey: ['priceBatch'] })
      return status
    },
    onSuccess: (status) => setStartStatus(status),
  })

  // Fired once per session shape: opening the summary is what queues the scrape, since scanning
  // itself only resolves the number. Re-entering the screen must not re-queue what is already done.
  useEffect(() => {
    if (!allLoaded || missing.length === 0) return
    if (batchSession.hasPriced(signature)) return
    batchSession.markPriced(signature)
    startPricing.mutate(missing)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the session, not the mutation
  }, [allLoaded, missing.length, signature])

  // Rows fill in one at a time as the server walks the queue: re-read the set it just left, and
  // sweep the lot once the run ends. Both are narrowed by a ref rather than firing on the value
  // itself — invalidating every row each time the server moves on is N² reads for one sweep, and
  // an unguarded "not running" refetches everything again the moment the page opens.
  const currentSetNum = batch.data?.currentSetNum ?? null
  const isRunning = batch.data?.isRunning ?? false
  const previousSetNumRef = useRef<string | null>(null)
  const wasRunningRef = useRef(false)

  useEffect(() => {
    const previous = previousSetNumRef.current
    previousSetNumRef.current = currentSetNum
    if (previous && previous !== currentSetNum) {
      queryClient.invalidateQueries({ queryKey: ['prices', previous] })
    }
  }, [currentSetNum, queryClient])

  useEffect(() => {
    if (wasRunningRef.current && !isRunning) {
      queryClient.invalidateQueries({ queryKey: ['prices'] })
    }
    wasRunningRef.current = isRunning
  }, [isRunning, queryClient])

  const cancel = useMutation({
    mutationFn: () => api.post('/prices/batch/cancel'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['priceBatch'] }),
  })

  /** Deal first, most negative first; everything unpriced trails in scan order, as on iOS. */
  const sorted = useMemo(() => {
    const decorated = items.map((set, index) => ({
      set,
      index,
      deal: bestDeal(prices.get(set.setNum)?.percentVsStore),
    }))
    return decorated.sort((a, b) => {
      if (a.deal && b.deal) return a.deal.percent - b.deal.percent
      if (!a.deal && !b.deal) return a.index - b.index
      return a.deal ? -1 : 1
    })
  }, [items, prices])

  const allSelected = items.length > 0 && items.every((item) => selected.has(item.setNum))
  const resolvedCount = items.length - missing.length
  const title =
    missing.length > 0 && isRunning
      ? `Session de scan (${resolvedCount}/${items.length})`
      : 'Session de scan'

  function toggle(setNum: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(setNum)) next.delete(setNum)
      else next.add(setNum)
      return next
    })
  }

  function leaveSelection() {
    setSelecting(false)
    setSelected(new Set())
  }

  async function run(action: { run: (setNums: string[]) => Promise<void> }) {
    setActionError(null)
    setBusy(true)
    try {
      await action.run([...selected])
      leaveSelection()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Action impossible')
    } finally {
      setBusy(false)
    }
  }

  if (items.length === 0) {
    return (
      <>
        <NavBar title="Session de scan" onBack={() => navigate('/scan')} backLabel="Retour au scanner" />
        <EmptyState
          icon={<Icon name="layers" className="h-9 w-9" />}
          title="Aucun set scanné"
          message="Scannez plusieurs sets en mode lot pour les comparer ici."
          action={
            <button type="button" className="btn-primary" onClick={() => navigate('/scan')}>
              Ouvrir le scanner
            </button>
          }
        />
      </>
    )
  }

  return (
    <div className={selecting ? 'pb-32' : 'pb-24'}>
      <NavBar
        title={title}
        onBack={() => navigate('/scan')}
        backLabel="Retour au scanner"
        actions={
          <button
            type="button"
            className="nav-pill text-[rgb(var(--negative))]"
            onClick={() => setConfirmClear(true)}
          >
            Vider
          </button>
        }
      />

      {actionError && <ErrorLabel message={actionError} className="mb-2" />}

      <Notice
        startStatus={startStatus}
        batch={batch.data}
        missingCount={missing.length}
        onRetry={() => startPricing.mutate(missing)}
        onCancel={() => cancel.mutate()}
      />

      <ul className="list-card">
        {sorted.map(({ set, deal }) => {
          const entry = prices.get(set.setNum)
          const isSelected = selected.has(set.setNum)
          return (
            <li key={set.setNum} className="border-b border-line last:border-0">
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-sunken"
                onClick={() =>
                  selecting
                    ? toggle(set.setNum)
                    : navigate(`/set/${encodeURIComponent(set.setNum)}`, {
                        // The whole session rides along, so the detail screen can page through it.
                        state: { siblings: sorted.map((row) => row.set.setNum) },
                      })
                }
              >
                <SetThumbnail url={set.setImgUrl} alt={set.name} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink">{baseSetNum(set.setNum)}</span>
                  <span className="block truncate text-[15px] text-ink-muted">{set.name}</span>
                </span>

                <span className="flex shrink-0 flex-col items-end gap-0.5 text-right">
                  <PriceColumn
                    entry={entry}
                    isCurrent={batch.data?.currentSetNum === set.setNum}
                    isRunning={isRunning}
                    queuePosition={missing.indexOf(set.setNum) + 1}
                    queueLength={missing.length}
                  />
                  {deal && (
                    <>
                      <span
                        className={`chip ${
                          deal.percent < 0
                            ? 'bg-[rgb(var(--positive))]/15 text-[rgb(var(--positive))]'
                            : 'bg-[rgb(var(--negative))]/15 text-[rgb(var(--negative))]'
                        }`}
                      >
                        {/* The arrow is the second channel: colour alone doesn't carry "good deal"
                            for a colour-blind reader. */}
                        {deal.percent < 0 ? '↓' : '↑'} {deal.percent > 0 ? '+' : ''}
                        {deal.percent} %
                      </span>
                      <span className="text-[11px] text-ink-faint">{SOURCE_LABEL[deal.source]}</span>
                    </>
                  )}
                </span>

                {selecting ? (
                  isSelected ? (
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-white">
                      <Icon name="check" className="h-3 w-3" />
                    </span>
                  ) : (
                    <span className="h-5 w-5 shrink-0 rounded-full border-2 border-line" />
                  )
                ) : (
                  <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-ink-faint" />
                )}
              </button>
            </li>
          )
        })}
      </ul>

      {!selecting && (
        <button
          type="button"
          className="fixed bottom-8 right-5 z-20 flex h-14 w-14 items-center justify-center rounded-full bg-surface-raised text-brand shadow-lg"
          onClick={() => setSelecting(true)}
          aria-label="Sélectionner des sets"
        >
          <Icon name="checklist" className="h-6 w-6" />
        </button>
      )}

      {selecting && (
        <div className="fixed inset-x-0 bottom-0 z-30 space-y-2 border-t border-line bg-surface/95 px-4 pb-6 pt-3 backdrop-blur">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="btn-ghost px-0"
              onClick={() =>
                setSelected(allSelected ? new Set() : new Set(items.map((item) => item.setNum)))
              }
            >
              {allSelected ? 'Tout désélectionner' : 'Tout sélectionner'}
            </button>
            <span className="text-[13px] text-ink-muted">{selected.size} sélectionné(s)</span>
            <div className="flex-1" />
            {busy && <Spinner className="h-4 w-4" />}
            <button type="button" className="btn-ghost px-0" onClick={leaveSelection}>
              Terminé
            </button>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[actions.addToCollection, actions.addToWishlist, actions.refreshPrices].map((action) => (
              <button
                key={action.key}
                type="button"
                className="btn-secondary px-2 text-[13px]"
                disabled={busy || selected.size === 0}
                onClick={() => run(action)}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <ListPickerSheet
        open={actions.listPicker.open}
        onPick={actions.listPicker.pick}
        onClose={actions.listPicker.cancel}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Vider la session"
        message="Les sets scannés seront retirés de la session. Les scans restent dans l'historique."
        confirmLabel="Vider"
        destructive
        onConfirm={() => {
          batchSession.clear()
          setConfirmClear(false)
          navigate('/scan')
        }}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  )
}

/**
 * The price the box is worth comparing against — the lego.com retail one, as on iOS. Three states
 * that must not be confused: priced, waiting its turn, and genuinely unavailable.
 */
function PriceColumn({
  entry,
  isCurrent,
  isRunning,
  queuePosition,
  queueLength,
}: {
  entry: SetPrices | undefined
  isCurrent: boolean
  isRunning: boolean
  queuePosition: number
  queueLength: number
}) {
  if (entry?.storePriceEur !== null && entry?.storePriceEur !== undefined) {
    return <span className="text-[15px] font-semibold text-ink">{formatEUR(entry.storePriceEur)}</span>
  }

  // lego.com can fail alone while BrickLink answers — the cheapest quote is still worth showing,
  // it just isn't a retail price and carries no ± badge.
  const cheapest = entry?.quotes.length
    ? entry.quotes.reduce((best, quote) => (quote.amount < best.amount ? quote : best))
    : null
  if (cheapest) {
    return (
      <>
        <span className="text-[15px] font-semibold text-ink-muted">{formatEUR(cheapest.amount)}</span>
        <span className="text-[11px] text-ink-faint">{SOURCE_LABEL[cheapest.source]}</span>
      </>
    )
  }

  if (isRunning) {
    return isCurrent ? (
      <span className="flex items-center gap-1 text-[11px] text-ink-muted">
        <Spinner className="h-3 w-3" /> Recherche…
      </span>
    ) : (
      // A spinner on every waiting row is what made the queue look frozen on iOS: only the set
      // actually being fetched spins, the rest say where they are in the line.
      <span className="flex items-center gap-1 text-[11px] text-ink-muted">
        <Icon name="clock" className="h-3 w-3" />
        En attente ({Math.max(queuePosition, 1)}/{Math.max(queueLength, 1)})
      </span>
    )
  }

  return <span className="text-[13px] text-ink-muted">Prix indisponible</span>
}

/** One line explaining what the price queue is doing — including "nothing, and here is why". */
function Notice({
  startStatus,
  batch,
  missingCount,
  onRetry,
  onCancel,
}: {
  startStatus: string | null
  batch: BatchStatus | undefined
  missingCount: number
  onRetry: () => void
  onCancel: () => void
}) {
  if (batch?.isRunning) {
    // The updater is process-wide: a run started from Réglages or by the background alert watch
    // owns the same queue, and its done/total say nothing about this session.
    const isOurs = batch.mode === 'selection'
    return (
      <p className="mb-2 flex items-center gap-2 px-1 text-[13px] text-ink-muted">
        <Spinner className="h-3.5 w-3.5" />
        {isOurs ? (
          <>
            Recherche des prix… ({batch.done}/{batch.total})
            <button type="button" className="btn-ghost px-2 py-0.5 text-[13px]" onClick={onCancel}>
              Arrêter
            </button>
          </>
        ) : (
          <>Une actualisation de la collection est en cours — les prix de la session arriveront ensuite.</>
        )}
      </p>
    )
  }

  if (startStatus === 'busy') {
    return (
      <p className="mb-2 flex items-center gap-2 px-1 text-[13px] text-ink-muted">
        Une actualisation des prix est déjà en cours — réessayez ensuite.
        <button type="button" className="btn-ghost px-2 py-0.5 text-[13px]" onClick={onRetry}>
          Réessayer
        </button>
      </p>
    )
  }

  if (missingCount > 0) {
    return (
      <div className="mb-2 px-1">
        <button type="button" className="btn-secondary px-3 py-1 text-[13px]" onClick={onRetry}>
          Actualiser les prix ({missingCount})
        </button>
      </div>
    )
  }

  return null
}
