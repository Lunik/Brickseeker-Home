import type { Valuation } from '../api/types'
import { CONDITION_LABEL, formatEUR, formatPercent, formatRelative } from '../lib/format'
import { Badge } from './ui'

const BASIS_LABEL: Record<Valuation['basis'], string> = {
  paid: 'prix payé',
  retail: 'prix lego.com',
  unknown: 'aucune référence',
}

/**
 * Current value and how it compares to what the set cost.
 *
 * The reference follows one rule: the price paid when recorded, the lego.com retail price
 * otherwise, and *nothing else*. A marketplace quote is never promoted to reference — it says what
 * the set is worth now, not what it cost, so using one would compare two market readings instead
 * of measuring a gain. That is why a minifig shows "—" until a paid price is entered.
 */
export default function ValuationCard({
  valuation,
  onEditPaidPrice,
}: {
  valuation: Valuation
  onEditPaidPrice: () => void
}) {
  const growth = valuation.growthPercent

  return (
    <section className="card space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="section-title">Valeur estimée</h2>
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onEditPaidPrice}>
          Prix payé
        </button>
      </div>

      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-2xl font-bold text-ink">{formatEUR(valuation.currentValueEur)}</p>
          <p className="text-xs text-ink-faint">
            {valuation.valuedCondition ? `valeur ${CONDITION_LABEL[valuation.valuedCondition].toLowerCase()}` : '—'}
            {valuation.asOf && ` · ${formatRelative(valuation.asOf)}`}
            {valuation.isStale && ' · à rafraîchir'}
          </p>
        </div>

        {growth !== null ? (
          <div className="text-right">
            <Badge tone={growth > 0 ? 'positive' : growth < 0 ? 'negative' : 'neutral'}>
              {formatPercent(growth, 1)}
            </Badge>
            <p className="mt-1 text-xs text-ink-faint">
              vs {formatEUR(valuation.basisEur)} ({BASIS_LABEL[valuation.basis]})
            </p>
          </div>
        ) : (
          <p className="text-right text-xs text-ink-faint">
            Évolution indisponible
            <br />
            {valuation.currentValueEur === null ? 'aucun prix connu' : 'aucune référence'}
          </p>
        )}
      </div>
    </section>
  )
}
