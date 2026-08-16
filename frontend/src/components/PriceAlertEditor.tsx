import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { ListCondition, PriceAlert } from '../api/types'
import { CONDITION_LABEL, formatEUR } from '../lib/format'
import { ErrorLabel, Sheet } from './ui'

interface PriceAlertEditorProps {
  open: boolean
  onClose: () => void
  setNum: string
  setName: string
  existing?: PriceAlert | null
  /** Only used to preview the resulting amount while typing a percentage; the authoritative
   *  reference is resolved and frozen server-side at save time. */
  referenceHint?: { amount: number; sourceName: string } | null
}

export default function PriceAlertEditor({
  open,
  onClose,
  setNum,
  setName,
  existing,
  referenceHint,
}: PriceAlertEditorProps) {
  const queryClient = useQueryClient()
  const [condition, setCondition] = useState<ListCondition>(existing?.condition ?? 'newSet')
  const [mode, setMode] = useState<'amount' | 'percent'>(
    existing?.discountPercent != null ? 'percent' : 'amount',
  )
  const [amount, setAmount] = useState(existing?.thresholdEur?.toString() ?? '')
  const [percent, setPercent] = useState(existing?.discountPercent?.toString() ?? '')
  const [enabled, setEnabled] = useState(existing?.isEnabled ?? true)

  const save = useMutation({
    mutationFn: () =>
      api.put<PriceAlert>('/alerts', {
        setNum,
        condition,
        thresholdEur: mode === 'amount' ? Number(amount) : null,
        discountPercent: mode === 'percent' ? Number(percent) : null,
        isEnabled: enabled,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['set', setNum] })
      await queryClient.invalidateQueries({ queryKey: ['alerts'] })
      onClose()
    },
  })

  const reference = existing?.referencePriceEur
    ? { amount: existing.referencePriceEur, sourceName: existing.referenceSourceName ?? 'référence' }
    : referenceHint
  const previewed =
    mode === 'percent' && reference && percent
      ? reference.amount * (1 - Number(percent) / 100)
      : null

  const valid = mode === 'amount' ? Number(amount) > 0 : Number(percent) > 0 && Number(percent) < 100

  return (
    <Sheet
      open={open}
      title={`Alerte — ${setName}`}
      onClose={onClose}
      footer={
        <button
          type="button"
          className="btn-primary w-full"
          disabled={!valid || save.isPending}
          onClick={() => save.mutate()}
        >
          Enregistrer l'alerte
        </button>
      }
    >
      <div className="space-y-4">
        {/* One alert covers one condition. Neuf and occasion come from different sources, so an
            alert covering both could not say which one crossed. */}
        <div className="space-y-1.5">
          <span className="section-title">Condition surveillée</span>
          <div className="flex gap-2">
            {(['newSet', 'used'] as ListCondition[]).map((value) => (
              <button
                key={value}
                type="button"
                className={condition === value ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
                onClick={() => setCondition(value)}
              >
                {CONDITION_LABEL[value]}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <span className="section-title">Seuil</span>
          <div className="flex gap-2">
            <button
              type="button"
              className={mode === 'amount' ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
              onClick={() => setMode('amount')}
            >
              Montant
            </button>
            <button
              type="button"
              className={mode === 'percent' ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
              onClick={() => setMode('percent')}
            >
              Pourcentage
            </button>
          </div>
        </div>

        {mode === 'amount' ? (
          <label className="block space-y-1.5">
            <span className="section-title">Préviens-moi en dessous de (€)</span>
            <input
              className="input"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
        ) : (
          <label className="block space-y-1.5">
            <span className="section-title">Préviens-moi à partir de (% de remise)</span>
            <input
              className="input"
              type="number"
              inputMode="decimal"
              min="1"
              max="99"
              value={percent}
              onChange={(event) => setPercent(event.target.value)}
            />
            {reference ? (
              <span className="block text-xs text-ink-faint">
                Soit {previewed !== null ? formatEUR(previewed) : '—'}, calculé sur{' '}
                {formatEUR(reference.amount)} ({reference.sourceName}). Cette référence est figée à
                la création : elle ne suivra pas le marché.
              </span>
            ) : (
              <span className="block text-xs text-amber-600">
                Aucun prix de référence connu pour ce set — saisis plutôt un montant, ou rafraîchis
                les prix d'abord.
              </span>
            )}
          </label>
        )}

        <label className="flex items-center gap-2">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          <span className="text-sm text-ink">Alerte active</span>
        </label>

        <p className="text-xs text-ink-faint">
          En arrière-plan, seul BrickLink peut être interrogé : une alerte « occasion » est donc
          entièrement surveillée, une alerte « neuf » uniquement jusqu'à BrickLink neuf.
        </p>

        {save.isError && <ErrorLabel message={(save.error as Error).message} />}
      </div>
    </Sheet>
  )
}
