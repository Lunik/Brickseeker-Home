/**
 * Which quote makes a scanned box worth picking up — the port of iOS `BatchScanItem.bestDeal`.
 *
 * The server already computes each source's ±% against the lego.com price (`percentVsStore`), so
 * the only decision left is which of them wins. Two rules, both from the iOS original:
 *
 * - **New sources win outright.** A used listing being cheaper than retail is not the same claim
 *   as a discounted new one, and letting it take the ranking whenever it happened to be more
 *   negative made one badge stand for two different comparisons. BrickLink occasion is a fallback,
 *   used only when no new source quoted at all.
 * - **The source is part of the answer.** These are live scrapes; the detail screen re-fetches and
 *   can legitimately fail to reproduce the quote this one found. Named, the number still means
 *   something afterwards; unnamed, it looks like it corresponds to nothing.
 */

import type { PriceSourceKey } from '../api/types'

/** Fixed order, so equal percentages always resolve to the same winner. */
const NEW_SOURCES: PriceSourceKey[] = [
  'bricklinkNew',
  'amazon',
  'cdiscount',
  'cultura',
  'fnac',
  'kingJouet',
  'laGrandeRecre',
  'joueclub',
  'carrefour',
  'intermarche',
]
const USED_SOURCES: PriceSourceKey[] = ['bricklinkUsed']

export interface Deal {
  /** Negative is cheaper than lego.com. */
  percent: number
  source: PriceSourceKey
}

function bestIn(
  sources: PriceSourceKey[],
  percentVsStore: Partial<Record<PriceSourceKey, number>>,
): Deal | null {
  let best: Deal | null = null
  for (const source of sources) {
    const percent = percentVsStore[source]
    if (percent === undefined) continue
    if (best === null || percent < best.percent) best = { percent, source }
  }
  return best
}

/**
 * `null` whenever no comparison is possible — which is every set with no lego.com price, since the
 * percentage is *against* that price. Those sets sort last rather than pretending to a ranking.
 */
export function bestDeal(
  percentVsStore: Partial<Record<PriceSourceKey, number>> | undefined,
): Deal | null {
  if (!percentVsStore) return null
  return bestIn(NEW_SOURCES, percentVsStore) ?? bestIn(USED_SOURCES, percentVsStore)
}
