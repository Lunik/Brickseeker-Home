import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { PriceHistoryPoint, SoldSale } from '../api/types'
import { formatDate, formatEUR, SOURCE_LABEL } from '../lib/format'

const SERIES_COLORS = ['rgb(var(--brand))', '#0ea5e9', '#22c55e', '#f59e0b', '#a855f7']

/**
 * Our own daily readings as lines, plus BrickLink's realised sales as a scatter.
 *
 * The two are kept apart on purpose: the lines are this app's once-a-day reading of an average,
 * the scatter is third-party transactions. Merging them would change what the trend line means.
 */
export default function PriceHistoryChart({
  history,
  soldListings,
}: {
  history: PriceHistoryPoint[]
  soldListings: SoldSale[]
}) {
  const { rows, sources } = useMemo(() => {
    const byDay = new Map<string, Record<string, number | string>>()
    const seen = new Set<string>()
    for (const point of history) {
      const day = point.fetchedAt.slice(0, 10)
      seen.add(point.source)
      const row = byDay.get(day) ?? { day }
      row[point.source] = point.amount
      byDay.set(day, row)
    }
    return {
      rows: [...byDay.values()].sort((a, b) => String(a.day).localeCompare(String(b.day))),
      sources: [...seen],
    }
  }, [history])

  const sales = useMemo(
    () =>
      soldListings.map((sale) => ({
        time: Date.parse(sale.orderedAt),
        amount: sale.unitAmount,
      })),
    [soldListings],
  )

  // Below two points there is no trend to draw — an axis with a single dot reads as a bug.
  if (rows.length < 2 && sales.length === 0) return null

  return (
    <section className="card space-y-3">
      <h2 className="section-title">Évolution des prix</h2>

      {rows.length >= 2 && (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
            <XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={28} />
            <YAxis tick={{ fontSize: 10 }} width={54} tickFormatter={(value) => `${Math.round(value)} €`} />
            <Tooltip contentStyle={{ fontSize: 12 }} formatter={(value: number) => formatEUR(value)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {sources.map((source, index) => (
              <Line
                key={source}
                type="monotone"
                dataKey={source}
                name={SOURCE_LABEL[source] ?? source}
                stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}

      {sales.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-ink-faint">
            Ventes réalisées sur BrickLink (6 derniers mois)
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <ScatterChart margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
              <XAxis
                type="number"
                dataKey="time"
                domain={['dataMin', 'dataMax']}
                tick={{ fontSize: 10 }}
                tickFormatter={(value) => formatDate(new Date(value).toISOString())}
              />
              <YAxis
                type="number"
                dataKey="amount"
                tick={{ fontSize: 10 }}
                width={54}
                tickFormatter={(value) => `${Math.round(value)} €`}
              />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                formatter={(value: number) => formatEUR(value)}
                labelFormatter={(value: number) => formatDate(new Date(value).toISOString())}
              />
              <Scatter data={sales} fill="rgb(var(--brand))" />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}
