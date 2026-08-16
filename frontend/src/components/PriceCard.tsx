import type { PriceQuote, PriceSourceKey, SetDetail } from '../api/types'
import { AVAILABILITY_LABEL, formatEUR, formatRelative, SOURCE_LABEL } from '../lib/format'
import { Badge, Spinner } from './ui'

/**
 * The price card: every source as a consistent row.
 *
 * Amazon and Cdiscount are **separate rows here** — this is the per-set comparison screen, where
 * the user wants to see both. They collapse into one comparison point everywhere else (the list
 * screens and the valuation), which is a different question.
 */

const ROW_ORDER: PriceSourceKey[] = ['bricklinkNew', 'bricklinkUsed', 'amazon', 'cdiscount']

interface PriceCardProps {
  detail: SetDetail
  pricePerPartTarget: number
  isRefreshing: boolean
  onRefresh: () => void
  onRefreshStore: () => void
}

function percentVsStore(amount: number, storePrice: number | null): number | null {
  if (!storePrice || storePrice <= 0) return null
  return Math.round(((amount - storePrice) / storePrice) * 100)
}

function DeltaBadge({ percent }: { percent: number | null }) {
  if (percent === null || percent === 0) return null
  return (
    <Badge tone={percent < 0 ? 'positive' : 'negative'}>
      {percent > 0 ? '+' : ''}
      {percent} %
    </Badge>
  )
}

function QuoteRow({
  label,
  quote,
  storePrice,
}: {
  label: string
  quote: PriceQuote | undefined
  storePrice: number | null
}) {
  return (
    <li className="flex items-start justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{label}</p>
        {quote && (
          <p className="text-xs text-ink-faint">
            {quote.minAmount !== null && quote.maxAmount !== null && (
              <>
                {formatEUR(quote.minAmount)} – {formatEUR(quote.maxAmount)}
                {quote.lotCount !== null ? ` · ${quote.lotCount} lot(s)` : ''}
              </>
            )}
            {/* A quote resting on ≤2 lots *is* one atypical sale — worth saying so rather than
                presenting it as a market rate. */}
            {quote.isThinSample && <span className="text-amber-600"> · échantillon très faible</span>}
            {quote.isStale && quote.fetchedAt && <> · relevé {formatRelative(quote.fetchedAt)}</>}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {quote ? (
          <>
            <DeltaBadge percent={percentVsStore(quote.amount, storePrice)} />
            {quote.sourceUrl ? (
              <a
                href={quote.sourceUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="text-sm font-bold text-brand underline"
              >
                {formatEUR(quote.amount)}
              </a>
            ) : (
              <span className="text-sm font-bold text-ink">{formatEUR(quote.amount)}</span>
            )}
          </>
        ) : (
          <span className="text-sm text-ink-faint">Indisponible</span>
        )}
      </div>
    </li>
  )
}

export default function PriceCard({
  detail,
  pricePerPartTarget,
  isRefreshing,
  onRefresh,
  onRefreshStore,
}: PriceCardProps) {
  const bySource = new Map(detail.quotes.map((quote) => [quote.source, quote]))
  const storePrice = detail.storePriceEur

  const reference = detail.valuation.currentValueEur ?? storePrice
  const pricePerPart = reference && detail.set.numParts > 0 ? reference / detail.set.numParts : null

  return (
    <section className="card space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="section-title">Prix</h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="btn-ghost px-2 py-1 text-xs"
            onClick={onRefreshStore}
            disabled={isRefreshing}
          >
            lego.com
          </button>
          <button
            type="button"
            className="btn-secondary px-2 py-1 text-xs"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? <Spinner className="h-3.5 w-3.5" /> : 'Tout rafraîchir'}
          </button>
        </div>
      </div>

      <ul className="divide-y divide-line">
        <li className="flex items-start justify-between gap-3 py-2.5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">lego.com (officiel)</p>
            <p className="flex items-center gap-1.5 text-xs text-ink-faint">
              <Badge
                tone={
                  detail.availability === 'available'
                    ? 'positive'
                    : detail.availability === 'retired'
                      ? 'neutral'
                      : detail.availability === 'outOfStock'
                        ? 'warning'
                        : 'neutral'
                }
              >
                {AVAILABILITY_LABEL[detail.availability]}
              </Badge>
              {detail.storePriceFetchedAt && <>relevé {formatRelative(detail.storePriceFetchedAt)}</>}
            </p>
          </div>
          {/* A retired set can legitimately still show a price — the amount is never hidden
              because of the status. */}
          <span className="shrink-0 text-sm font-bold text-ink">
            {storePrice !== null ? formatEUR(storePrice) : 'Indisponible'}
          </span>
        </li>

        {ROW_ORDER.map((source) => (
          <QuoteRow
            key={source}
            label={SOURCE_LABEL[source]}
            quote={bySource.get(source)}
            storePrice={storePrice}
          />
        ))}

        {pricePerPart !== null && (
          <li className="flex items-center justify-between gap-3 py-2.5">
            <p className="text-sm font-medium text-ink">Prix par pièce</p>
            <span
              className={`text-sm font-bold ${
                pricePerPart <= pricePerPartTarget
                  ? 'text-[rgb(var(--positive))]'
                  : 'text-[rgb(var(--negative))]'
              }`}
            >
              {pricePerPart.toFixed(3)} € / pièce
              <span className="ml-1 text-xs font-normal text-ink-faint">
                (objectif {pricePerPartTarget.toFixed(2)} €)
              </span>
            </span>
          </li>
        )}
      </ul>

      {detail.storeUrl && (
        <div className="flex flex-wrap gap-2 pt-1">
          <a className="btn-ghost px-2 py-1 text-xs" href={detail.storeUrl} target="_blank" rel="noreferrer noopener">
            Voir sur lego.com
          </a>
          {detail.instructionsUrl && (
            <a
              className="btn-ghost px-2 py-1 text-xs"
              href={detail.instructionsUrl}
              target="_blank"
              rel="noreferrer noopener"
            >
              Notices de montage
            </a>
          )}
        </div>
      )}
    </section>
  )
}
