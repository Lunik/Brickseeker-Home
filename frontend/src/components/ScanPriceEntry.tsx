import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DealVerdictResult } from '../api/types'
import { formatEUR, formatRelative } from '../lib/format'
import { ErrorLabel, Sheet, Spinner } from './ui'

/**
 * "Quel prix as-tu vu ?" — the shelf price, weighed against every reference already loaded.
 *
 * The value recorded here means "seen with my own eyes" and is never backfilled from an online
 * price; it is also what seeds the paid price when the set later joins the collection.
 */
export default function ScanPriceEntry({
  open,
  onClose,
  setNum,
  scanEventId,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  setNum: string
  scanEventId?: number | null
  onSaved?: () => void
}) {
  const [price, setPrice] = useState('')
  const [verdict, setVerdict] = useState<DealVerdictResult | null>(null)

  const evaluate = useMutation({
    mutationFn: (amount: number) =>
      api.post<DealVerdictResult>('/prices/deal-verdict', { setNum, priceSeen: amount }),
    onSuccess: (result) => setVerdict(result.verdict ? result : null),
  })

  const save = useMutation({
    mutationFn: (amount: number) =>
      scanEventId
        ? api.patch(`/history/events/${scanEventId}`, { priceSeenEur: amount })
        : api.post('/history/events', { setNum, priceSeenEur: amount }),
    onSuccess: () => {
      onSaved?.()
      onClose()
    },
  })

  const amount = Number(price.replace(',', '.'))
  const valid = amount > 0

  useEffect(() => {
    if (!open) return
    setPrice('')
    setVerdict(null)
  }, [open, setNum])

  return (
    <Sheet
      open={open}
      title="Prix vu en magasin"
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary flex-1"
            disabled={!valid || evaluate.isPending}
            onClick={() => evaluate.mutate(amount)}
          >
            {evaluate.isPending ? <Spinner className="h-4 w-4" /> : 'Évaluer'}
          </button>
          <button
            type="button"
            className="btn-primary flex-1"
            disabled={!valid || save.isPending}
            onClick={() => save.mutate(amount)}
          >
            Enregistrer
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <label className="block space-y-1.5">
          <span className="section-title">Prix affiché (€)</span>
          <input
            className="input"
            autoFocus
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={price}
            onChange={(event) => {
              setPrice(event.target.value)
              setVerdict(null)
            }}
          />
        </label>

        {verdict && (
          <div className="space-y-2 rounded-xl bg-surface-sunken p-3">
            <p className="text-base font-bold text-ink">
              {verdict.emoji} {verdict.label}
            </p>
            <ul className="space-y-1 text-sm">
              {verdict.comparisons.map((comparison) => (
                <li key={comparison.label} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate text-ink-muted">
                    {comparison.label}
                    {comparison.fetchedAt && (
                      <span className="text-xs text-ink-faint"> · {formatRelative(comparison.fetchedAt)}</span>
                    )}
                  </span>
                  <span
                    className={
                      comparison.percent < 0
                        ? 'shrink-0 font-semibold text-[rgb(var(--positive))]'
                        : 'shrink-0 font-semibold text-[rgb(var(--negative))]'
                    }
                  >
                    {comparison.percent > 0 ? '+' : ''}
                    {comparison.percent} % ({formatEUR(comparison.referenceAmount)})
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {evaluate.isError && <ErrorLabel message={(evaluate.error as Error).message} />}
        {save.isError && <ErrorLabel message={(save.error as Error).message} />}
      </div>
    </Sheet>
  )
}
