import type { PriceQuote, PriceSourceKey, SetDetail } from '../api/types'
import { AVAILABILITY_LABEL, formatEUR, formatRelative, SOURCE_LABEL } from '../lib/format'
import Icon from './Icon'
import { Badge, Spinner } from './ui'

/**
 * The price card: every source as a consistent row.
 *
 * External retail sources are **separate rows here** — this is the per-set comparison screen, where
 * the user wants to see each quote. They collapse into one comparison point everywhere else (the
 * list screens and the valuation), which is a different question.
 */

const ROW_ORDER: PriceSourceKey[] = [
  'bricklinkNew',
  'bricklinkUsed',
  'amazon',
  'cdiscount',
  'cultura',
  'smythToys',
  'kingJouet',
  'laGrandeRecre',
  'joueclub',
]
/**
 * A minifig is only ever sold on BrickLink — never at retail, which is why `resolve_minifig_price`
 * reads BrickLink alone. The backend already declines to scrape lego.com/retail sites for one
 * (`services/prices.py`), so those rows could never fill: they stood there reading « Indisponible »
 * for good, dead lines implying a price might turn up.
 */
const MINIFIG_ROW_ORDER: PriceSourceKey[] = ['bricklinkNew', 'bricklinkUsed']

interface PriceCardProps {
  detail: SetDetail
  pricePerPartTarget: number
  isRefreshing: boolean
  activeSources: string[]
  onRefresh: () => void
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
  captchaRequired,
  isLoading,
}: {
  label: string
  quote: PriceQuote | undefined
  storePrice: number | null
  captchaRequired: boolean
  isLoading: boolean
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
            {captchaRequired && (
              <p className="text-xs text-amber-600">CAPTCHA requis pour actualiser cette source</p>
            )}
            {/* A quote resting on ≤2 lots *is* one atypical sale — worth saying so rather than
                presenting it as a market rate. */}
            {quote.isThinSample && <span className="text-amber-600"> · échantillon très faible</span>}
            {quote.isStale && quote.fetchedAt && <> · relevé {formatRelative(quote.fetchedAt)}</>}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {isLoading && (
          <>
            <Spinner className="h-4 w-4 text-brand" />
            <span className="sr-only">{label} en cours de chargement</span>
          </>
        )}
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
        ) : captchaRequired ? (
          <span className="text-sm font-medium text-amber-600">CAPTCHA requis</span>
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
  activeSources,
  onRefresh,
}: PriceCardProps) {
  const bySource = new Map(detail.quotes.map((quote) => [quote.source, quote]))
  // A minifig has no retail price, so there is nothing for the ± badges to compare against either.
  const storePrice = detail.isMinifig ? null : detail.storePriceEur

  const reference = detail.valuation.currentValueEur ?? storePrice
  const pricePerPart = reference && detail.set.numParts > 0 ? reference / detail.set.numParts : null
  const isSourceLoading = (source: PriceSourceKey | 'legoStore') =>
    activeSources.includes(source === 'bricklinkNew' || source === 'bricklinkUsed' ? 'bricklink' : source)

  return (
    <section className="card space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="section-title">Prix</h2>
        {/* One icon, as in the iOS price header. The separate "lego.com" button that re-read only
            the store price is gone: a second control for a subset of what this one does was more
            explaining than it was worth, and this refresh covers it. */}
        <button
          type="button"
          className="nav-circle h-9 w-9"
          onClick={onRefresh}
          disabled={isRefreshing}
          aria-label="Rafraîchir les prix"
          title="Rafraîchir les prix"
        >
          {isRefreshing ? <Spinner className="h-4 w-4" /> : <Icon name="refresh" className="h-4 w-4" />}
        </button>
      </div>
      <ul className="divide-y divide-line">
        {!detail.isMinifig && (
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
          <span className="flex shrink-0 items-center gap-2 text-sm font-bold text-ink">
            {isSourceLoading('legoStore') && (
              <>
                <Spinner className="h-4 w-4 text-brand" />
                <span className="sr-only">lego.com en cours de chargement</span>
              </>
            )}
            {storePrice !== null ? formatEUR(storePrice) : 'Indisponible'}
          </span>
        </li>
        )}

        {/* Directly under the retail price it is derived from, as on iOS — at the bottom of the
            list it read as a summary of every source, which it is not. */}
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

        {(detail.isMinifig ? MINIFIG_ROW_ORDER : ROW_ORDER).map((source) => (
          <QuoteRow
            key={source}
            label={SOURCE_LABEL[source]}
            quote={bySource.get(source)}
            storePrice={storePrice}
            captchaRequired={detail.captchaRequiredSources?.includes(source) ?? false}
            isLoading={isSourceLoading(source)}
          />
        ))}
      </ul>
      {/* No links here: lego.com and the building instructions are both in the "Liens" card at the
          foot of the screen, where everything that leaves the app is grouped. */}
    </section>
  )
}
