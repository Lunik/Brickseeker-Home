import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BatchStatus } from '../api/types'
import { formatPriceSources } from '../lib/format'
import { ProgressBar } from './ui'

/**
 * Surfaces the collection-wide price batch on the list screens that can start it (Collection,
 * Historique, Liste cadeaux, Nouveaux sets) — not just in Réglages/Statistiques.
 *
 * A batch started from a multi-select here runs entirely server-side and out of sight; without
 * this, hitting a CAPTCHA left no trace on the very screen the selection was made from, only in
 * Réglages. The batch is collection-wide by design (`price_updater.py` is a single serial queue),
 * so the same status applies no matter which list screen kicked it off.
 */
export default function PriceBatchBanner() {
  const batch = useQuery({
    queryKey: ['priceBatch'],
    queryFn: () => api.get<BatchStatus>('/prices/batch/status'),
    refetchInterval: (query) => (query.state.data?.isRunning ? 2000 : false),
  })

  if (!batch.data) return null

  const captchaSources = batch.data.captchaRequiredSources
  if (!batch.data.isRunning && captchaSources.length === 0) return null

  return (
    <div className="space-y-1.5 rounded-2xl border border-line bg-surface px-3 py-2.5">
      {batch.data.isRunning && (
        <>
          <div className="flex items-center justify-between text-[13px] text-ink-muted">
            <span>
              Actualisation des prix : {batch.data.done} / {batch.data.total}
              {batch.data.currentSetNum ? ` · ${batch.data.currentSetNum}` : ''}
            </span>
          </div>
          <ProgressBar value={batch.data.done} total={batch.data.total} />
        </>
      )}
      {captchaSources.length > 0 && (
        <p className="text-[13px] text-amber-500">
          CAPTCHA requis : {formatPriceSources(captchaSources)}. Ouvrez la fiche d’un set concerné
          et actualisez-la manuellement pour le débloquer.
        </p>
      )}
    </div>
  )
}
