import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { PriceHistoryPoint, SoldSale } from '../api/types'
import { formatDate, formatEUR, SOURCE_LABEL } from '../lib/format'

/** Fixed per source, not by index: a source appearing or disappearing must not recolour the rest. */
const SOURCE_COLORS: Record<string, string> = {
  bricklinkNew: '#f59e0b',
  bricklinkUsed: '#0ea5e9',
  legoStore: '#22c55e',
  amazon: '#a855f7',
  cdiscount: '#ec4899',
}
const FALLBACK_COLOR = 'rgb(var(--brand))'

/** The realised-sales series. Deliberately not a source colour — it is third-party evidence. */
const SALES_KEY = 'sale'
const SALES_COLOR = '#94a3b8'
const SALES_LABEL = 'Ventes réalisées (BrickLink)'

/**
 * One chart: our own daily readings as lines, BrickLink's realised sales as dots, sharing a time
 * axis and a euro axis.
 *
 * They were two stacked charts, on the grounds that a reading of an average and a transaction are
 * different things — but two axes with different scales sitting one above the other invited exactly
 * the comparison they were meant to prevent, and made neither readable. On one pair of axes the
 * comparison is at least honest, and the legend lets any series be taken out of the way.
 */
export default function PriceHistoryChart({
  history,
  soldListings,
}: {
  history: PriceHistoryPoint[]
  soldListings: SoldSale[]
}) {
  /**
   * The one series shown alone, or `null` for "show everything".
   *
   * Isolating beats hiding one at a time: with six series on a phone, reading one of them means
   * getting the other five out of the way, and that was five taps. One tap in, one tap out.
   */
  const [soloed, setSoloed] = useState<string | null>(null)
  const isHidden = (key: string) => soloed !== null && soloed !== key

  const { rows, sources, pointCounts, saleCount } = useMemo(() => {
    // One row per day for the lines, one row per sale for the scatter, merged on a numeric time
    // axis. A single `data` array rather than per-series `data` props: the axis then derives its
    // domain from everything on screen, and no series can silently fall outside it.
    const byDay = new Map<string, Record<string, number>>()
    const seen = new Set<string>()
    const counts: Record<string, number> = {}
    for (const point of history) {
      const day = point.fetchedAt.slice(0, 10)
      seen.add(point.source)
      // Midday, so a point lands inside its day rather than on the boundary with the previous one.
      const row = byDay.get(day) ?? { time: Date.parse(`${day}T12:00:00Z`) }
      if (!(point.source in row)) counts[point.source] = (counts[point.source] ?? 0) + 1
      row[point.source] = point.amount
      byDay.set(day, row)
    }

    const sales = soldListings.map((sale) => ({
      time: Date.parse(sale.orderedAt),
      [SALES_KEY]: sale.unitAmount,
    }))

    return {
      rows: [...byDay.values(), ...sales].sort((a, b) => a.time - b.time),
      sources: [...seen],
      pointCounts: counts,
      saleCount: sales.length,
    }
  }, [history, soldListings])

  const series = useMemo(
    () => [
      ...sources.map((source) => ({
        key: source,
        label: SOURCE_LABEL[source] ?? source,
        color: SOURCE_COLORS[source] ?? FALLBACK_COLOR,
      })),
      ...(saleCount > 0 ? [{ key: SALES_KEY, label: SALES_LABEL, color: SALES_COLOR }] : []),
    ],
    [sources, saleCount],
  )

  // Hiding a series has to take its rows with it, or the time axis keeps spanning six months of
  // sales that are no longer drawn and squeezes what is left into the last pixel column.
  const visibleRows = rows.filter((row) =>
    Object.keys(row).some((key) => key !== 'time' && !isHidden(key)),
  )

  // Below two points there is no trend to draw — an axis with a single dot reads as a bug.
  if (rows.length < 2) return null

  return (
    <section className="card space-y-3">
      <h2 className="section-title">Évolution des prix</h2>

      <ResponsiveContainer width="100%" height={230}>
        <ComposedChart data={visibleRows} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
          <XAxis
            type="number"
            dataKey="time"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tick={{ fontSize: 10, fill: 'rgb(var(--ink-faint))' }}
            minTickGap={28}
            tickFormatter={(value: number) => formatDate(new Date(value).toISOString())}
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'rgb(var(--ink-faint))' }}
            width={54}
            tickFormatter={(value: number) => `${Math.round(value)} €`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'rgb(var(--surface-raised))',
              border: '1px solid rgb(var(--line))',
              borderRadius: 12,
              fontSize: 12,
            }}
            itemStyle={{ color: 'rgb(var(--ink))' }}
            labelStyle={{ color: 'rgb(var(--ink-muted))' }}
            cursor={{ stroke: 'rgb(var(--line))' }}
            formatter={(value: number) => formatEUR(value)}
            labelFormatter={(value: number) => formatDate(new Date(value).toISOString())}
          />
          {sources.map((source) => (
            <Line
              key={source}
              type="monotone"
              dataKey={source}
              name={SOURCE_LABEL[source] ?? source}
              stroke={SOURCE_COLORS[source] ?? FALLBACK_COLOR}
              strokeWidth={2}
              // A source read once — a set only just added — has no segment to draw, and drew
              // nothing at all: an empty chart claiming there is no history. Its single reading
              // gets a dot instead. Past a few days the dots become clutter, so they stop.
              dot={(pointCounts[source] ?? 0) < 4 ? { r: 3 } : false}
              // The sale rows carry no reading, so without this every line breaks at each sale.
              connectNulls
              hide={isHidden(source)}
            />
          ))}
          {saleCount > 0 && (
            <Scatter
              dataKey={SALES_KEY}
              name={SALES_LABEL}
              fill={SALES_COLOR}
              hide={isHidden(SALES_KEY)}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>

      {/* The legend is the filter: tapping an entry leaves that series alone on the chart, and
          tapping it again brings the others back. */}
      <ul className="flex flex-wrap gap-x-3 gap-y-1.5">
        {series.map((item) => {
          const dimmed = isHidden(item.key)
          const isSoloed = soloed === item.key
          return (
            <li key={item.key}>
              <button
                type="button"
                className={`flex items-center gap-1.5 text-[11px] ${
                  dimmed ? 'text-ink-faint line-through' : isSoloed ? 'font-semibold text-ink' : 'text-ink-muted'
                }`}
                onClick={() => setSoloed((current) => (current === item.key ? null : item.key))}
                aria-pressed={isSoloed}
                title={isSoloed ? 'Afficher toutes les séries' : `Afficher seulement ${item.label}`}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: dimmed ? 'rgb(var(--ink-faint))' : item.color }}
                />
                {item.label}
              </button>
            </li>
          )
        })}
      </ul>

      {soloed !== null && (
        <p className="text-[11px] text-ink-faint">
          Une seule série affichée — touchez-la de nouveau pour toutes les revoir.
        </p>
      )}

      {saleCount > 0 && (
        <p className="text-[11px] text-ink-faint">
          Les lignes sont les relevés quotidiens de l'app ; les points sont des ventes réellement
          conclues sur BrickLink ces six derniers mois.
        </p>
      )}
    </section>
  )
}
