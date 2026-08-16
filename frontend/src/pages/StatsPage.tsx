import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '../api/client'
import type { CollectionStats } from '../api/types'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, LoadingBlock } from '../components/ui'
import { formatEUR, formatEURCompact, formatNumber } from '../lib/format'

const CHART_HEIGHT = 220
/** Beyond this the bar labels stop being readable on a phone; the rest is grouped as "Autres". */
const MAX_THEME_BARS = 8

export default function StatsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<CollectionStats>('/stats'),
  })

  const completeMissing = useMutation({
    mutationFn: () => api.post('/prices/batch/start', { onlyMissing: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['priceBatch'] }),
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorLabel message={(error as Error).message} />
  if (!data || data.setCount === 0) {
    return (
      <EmptyState
        icon={<Icon name="chart" className="h-9 w-9" />}
        title="Pas encore de statistiques"
        message="Synchronise ta collection Rebrickable pour voir sa répartition et sa valeur estimée."
        action={
          <button type="button" className="btn-primary" onClick={() => navigate('/collection')}>
            Ouvrir la collection
          </button>
        }
      />
    )
  }

  const themes = [...data.themeBreakdown]
  const topThemes = themes.slice(0, MAX_THEME_BARS)
  const rest = themes.slice(MAX_THEME_BARS)
  if (rest.length) {
    topThemes.push({
      themeId: -1,
      themeName: 'Autres',
      setCount: rest.reduce((total, theme) => total + theme.setCount, 0),
      partCount: rest.reduce((total, theme) => total + theme.partCount, 0),
    })
  }

  const valuePoints = data.valueSnapshots.map((snapshot) => ({
    day: snapshot.dayKey,
    value: snapshot.totalValueEur,
    reliable: snapshot.isReliable,
  }))

  const coverage = data.setCount ? Math.round((data.setsWithKnownPrice / data.setCount) * 100) : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[34px] font-bold leading-tight text-ink">Statistiques</h1>
        <button
          type="button"
          className="nav-circle"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['stats'] })}
          aria-label="Actualiser la valeur estimée"
        >
          <Icon name="refresh" />
        </button>
      </div>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Figure label="Sets" value={formatNumber(data.setCount)} />
        <Figure label="Exemplaires" value={formatNumber(data.unitCount)} />
        <Figure label="Pièces" value={formatNumber(data.partCount)} />
        <Figure label="Thèmes" value={formatNumber(data.themeCount)} />
        <div className="card col-span-2 sm:col-span-1">
          <p className="text-sm text-ink-muted">Valeur estimée</p>
          <p className="text-2xl font-bold text-ink">{formatEURCompact(data.totalValueEur)}</p>
          {/* An estimated total is only honest next to its coverage. */}
          <p className="text-xs text-ink-faint">
            {data.setsWithKnownPrice} / {data.setCount} sets valorisés ({coverage} %)
          </p>
        </div>
      </section>

      {data.setsWithKnownPrice < data.setCount && (
        <button
          type="button"
          className="btn-secondary w-full"
          onClick={() => completeMissing.mutate()}
          disabled={completeMissing.isPending}
        >
          Compléter les prix manquants ({data.setCount - data.setsWithKnownPrice} set(s))
        </button>
      )}

      <section className="space-y-2">
        <h2 className="section-title">Sets par thème</h2>
        <div className="card">
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <BarChart data={topThemes} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
              <XAxis dataKey="themeName" tick={{ fontSize: 10 }} interval={0} angle={-35} textAnchor="end" height={64} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="section-title">Sets par période</h2>
        <div className="card">
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <BarChart data={data.yearBreakdown} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="mt-1 text-xs text-ink-faint">
            Regroupé par tranches de 5 ans — une barre par année serait illisible sur téléphone.
          </p>
        </div>
      </section>

      {valuePoints.length > 1 && (
        <section className="space-y-2">
          <h2 className="section-title">Valeur de la collection</h2>
          <div className="card">
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <LineChart data={valuePoints} margin={{ top: 4, right: 8, bottom: 4, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
                <XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={24} />
                <YAxis tick={{ fontSize: 10 }} width={64} tickFormatter={(value) => formatEURCompact(value)} />
                <Tooltip contentStyle={{ fontSize: 12 }} formatter={(value: number) => formatEUR(value)} />
                <Line
                  type="monotone"
                  dataKey="value"
                  name="Valeur"
                  stroke="rgb(var(--brand))"
                  strokeWidth={2}
                  dot={(props) => {
                    const { cx, cy, payload, index } = props as {
                      cx: number
                      cy: number
                      index: number
                      payload: { reliable: boolean }
                    }
                    // A thin-coverage day is real but understates the collection: greyed rather
                    // than drawn like any other point, which would show a crash that never happened.
                    return (
                      <circle
                        key={index}
                        cx={cx}
                        cy={cy}
                        r={3}
                        fill={payload.reliable ? 'rgb(var(--brand))' : 'rgb(var(--ink-faint))'}
                      />
                    )
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
            <p className="mt-1 text-xs text-ink-faint">
              Les points gris correspondent aux jours où moins de 80 % de la collection avait un prix.
            </p>
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="section-title">Superlatifs</h2>
        <div className="space-y-2">
          {data.mostExpensiveSet && (
            <Superlative
              label="Le plus cher"
              set={data.mostExpensiveSet.name}
              detail={formatEUR(data.mostExpensiveSetPriceEur)}
              onClick={() => navigate(`/set/${encodeURIComponent(data.mostExpensiveSet!.setNum)}`)}
            />
          )}
          {data.oldestSet && (
            <Superlative
              label="Le plus ancien"
              set={data.oldestSet.name}
              detail={String(data.oldestSet.year)}
              onClick={() => navigate(`/set/${encodeURIComponent(data.oldestSet!.setNum)}`)}
            />
          )}
          {data.largestSet && (
            <Superlative
              label="Le plus grand"
              set={data.largestSet.name}
              detail={`${formatNumber(data.largestSet.numParts)} pièces`}
              onClick={() => navigate(`/set/${encodeURIComponent(data.largestSet!.setNum)}`)}
            />
          )}
        </div>
      </section>

      <button type="button" className="btn-ghost w-full" onClick={() => navigate('/collection')}>
        Configurer le type (neuf/occasion) des listes
      </button>

      <section className="space-y-2">
        <h2 className="section-title">Export</h2>
        <div className="flex gap-2">
          <a className="btn-secondary flex-1" href="/api/stats/export.csv">
            Export CSV
          </a>
          <a className="btn-secondary flex-1" href="/api/stats/export.pdf">
            Export PDF
          </a>
        </div>
      </section>
    </div>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className="text-2xl font-bold text-ink">{value}</p>
    </div>
  )
}

function Superlative({
  label,
  set,
  detail,
  onClick,
}: {
  label: string
  set: string
  detail: string
  onClick: () => void
}) {
  return (
    <button type="button" className="card flex w-full items-center gap-3 text-left" onClick={onClick}>
      <span className="min-w-0 flex-1">
        <span className="block text-xs text-ink-faint">{label}</span>
        <span className="block truncate font-semibold text-ink">{set}</span>
      </span>
      <span className="shrink-0 text-sm font-bold text-brand">{detail}</span>
    </button>
  )
}
