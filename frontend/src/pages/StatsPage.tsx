import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '../api/client'
import type { CollectionStats, SetRow } from '../api/types'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, LoadingBlock, NavBar, Spinner } from '../components/ui'
import { formatEUR, formatEURCompact, formatNumber } from '../lib/format'

/** Beyond this the theme labels stop being readable on a phone; the rest is grouped as "Autres". */
const MAX_THEME_BARS = 10

export default function StatsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<CollectionStats>('/stats'),
  })

  const completeMissing = useMutation({
    mutationFn: async () => {
      const { status } = await api.post<{ status: string }>('/prices/batch/start', { onlyMissing: true })
      if (status === 'busy') throw new Error('Une actualisation des prix est déjà en cours.')
      if (status === 'empty') throw new Error('Aucun prix à compléter — toutes les sources ont déjà été interrogées.')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['priceBatch'] }),
  })

  // The iOS button of the same name runs a real refresh over the collection; re-reading cached
  // figures would leave the value unchanged and the button looking broken.
  const refreshValue = useMutation({
    mutationFn: async () => {
      const { status } = await api.post<{ status: string }>('/prices/batch/start', {})
      if (status === 'busy') throw new Error('Une actualisation des prix est déjà en cours.')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['priceBatch'] }),
  })

  const batch = useQuery({
    queryKey: ['priceBatch'],
    queryFn: () => api.get<{ isRunning: boolean; done: number; total: number }>('/prices/batch/status'),
    refetchInterval: (q) => (q.state.data?.isRunning ? 2000 : false),
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorLabel message={(error as Error).message} />
  if (!data || data.setCount === 0) {
    return (
      <>
        <NavBar title="Statistiques" />
        <EmptyState
          icon={<Icon name="chart" className="h-10 w-10" />}
          title="Aucune statistique"
          message="Liez votre compte Rebrickable et synchronisez depuis l'accueil."
          action={
            <button type="button" className="btn-primary" onClick={() => navigate('/')}>
              Retour à l'accueil
            </button>
          }
        />
      </>
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

  // The server's count of sets a run would actually process — the naive
  // `setCount - setsWithKnownPrice` included sets already tried against every source.
  const missing = data.completablePriceCount

  return (
    <div className="space-y-6 pb-10">
      <NavBar
        title="Statistiques"
        actions={
          <button
            type="button"
            className="nav-circle"
            onClick={() => refreshValue.mutate()}
            disabled={isFetching || batch.data?.isRunning}
            aria-label="Actualiser la valeur estimée"
          >
            <Icon name="refresh" />
          </button>
        }
      />

      <section className="space-y-3">
        <h2 className="text-[22px] font-bold text-ink">Totaux</h2>
        <div className="grid grid-cols-3 gap-3">
          <Total icon="box" value={formatNumber(data.setCount)} label="Sets" />
          <Total icon="brick" value={formatNumber(data.partCount)} label="Pièces" />
          <Total icon="tag" value={formatNumber(data.themeCount)} label="Thèmes" />
        </div>
      </section>

      <section className="card space-y-2">
        <h2 className="text-[20px] font-bold text-ink">Répartition par année</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data.yearBreakdown} margin={{ top: 8, right: 4, bottom: 4, left: -18 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }} />
            <YAxis
              orientation="right"
              tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }}
              allowDecimals={false}
            />
            <Tooltip contentStyle={{ fontSize: 12 }} />
            <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" />
          </BarChart>
        </ResponsiveContainer>
      </section>

      {/* Horizontal bars with the theme name above each, as on iOS — a vertical chart truncates
          theme names to unreadable stubs at phone width. */}
      <section className="card space-y-2">
        <h2 className="text-[20px] font-bold text-ink">Répartition par thème</h2>
        <ResponsiveContainer width="100%" height={Math.max(220, topThemes.length * 52)}>
          <BarChart
            data={topThemes}
            layout="vertical"
            margin={{ top: 8, right: 8, bottom: 4, left: 4 }}
            barCategoryGap={18}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }} allowDecimals={false} />
            <YAxis type="category" dataKey="themeName" hide />
            <Tooltip contentStyle={{ fontSize: 12 }} />
            <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" barSize={12} radius={[0, 3, 3, 0]}>
              {/* The theme name sits above its own bar, as on iOS — a category axis would squeeze
                  every label into a truncated left gutter at phone width. */}
              <LabelList
                dataKey="themeName"
                position="top"
                offset={8}
                style={{ fill: 'rgb(var(--ink-muted))', fontSize: 12 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </section>

      <section className="card space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-[20px] font-bold text-ink">Valeur estimée</h2>
        </div>
        <p className="text-[28px] font-bold text-ink">{formatEUR(data.totalValueEur)}</p>
        {/* An estimated total is only honest next to its coverage. */}
        <p className="text-[13px] text-ink-muted">
          Basée sur {data.setsWithKnownPrice} / {data.setCount} sets ({data.pricedUnitCount} /{' '}
          {data.unitCount} exemplaires) dont le prix est connu
        </p>
        {batch.data?.isRunning && (
          <p className="flex items-center gap-2 text-[13px] text-ink-muted">
            <Spinner className="h-3 w-3" /> Actualisation : {batch.data.done} / {batch.data.total}
          </p>
        )}
        {(completeMissing.isError || refreshValue.isError) && (
          <ErrorLabel
            message={((completeMissing.error ?? refreshValue.error) as Error).message}
            className="text-[13px]"
          />
        )}
        {missing > 0 && (
          <button
            type="button"
            className="btn-ghost w-full justify-start px-0 text-left"
            onClick={() => completeMissing.mutate()}
            disabled={completeMissing.isPending}
          >
            Compléter les prix manquants ({missing})
          </button>
        )}
        <button
          type="button"
          className="btn-ghost w-full justify-between gap-2 px-0 text-left"
          onClick={() => navigate('/collection')}
        >
          Configurer le type (neuf/occasion) des listes
          <Icon name="chevron-right" className="h-4 w-4" />
        </button>
      </section>

      {valuePoints.length > 1 && (
        <section className="card space-y-2">
          <h2 className="text-[20px] font-bold text-ink">Valeur de la collection</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={valuePoints} margin={{ top: 8, right: 8, bottom: 4, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }} minTickGap={24} />
              <YAxis
                tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }}
                width={64}
                tickFormatter={(value) => formatEURCompact(value)}
              />
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
                  // A thin-coverage day is real but understates the collection: greyed rather than
                  // drawn like any other point, which would show a crash that never happened.
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
          <p className="text-[13px] text-ink-faint">
            Les points grisés reposent sur une couverture de prix partielle : tous les sets n'avaient
            pas de prix connu à cette date.
          </p>
        </section>
      )}

      <section className="card space-y-1">
        <h2 className="text-[20px] font-bold text-ink">Superlatifs</h2>
        <Superlative
          label="Le plus cher"
          set={data.mostExpensiveSet}
          detail={formatEUR(data.mostExpensiveSetPriceEur)}
          onOpen={navigate}
        />
        <Superlative
          label="Le plus ancien"
          set={data.oldestSet}
          detail={data.oldestSet ? String(data.oldestSet.year) : ''}
          onOpen={navigate}
        />
        <Superlative
          label="Le plus de pièces"
          set={data.largestSet}
          detail={data.largestSet ? `${formatNumber(data.largestSet.numParts)} pièces` : ''}
          onOpen={navigate}
        />
      </section>

      <section className="card space-y-2">
        <h2 className="text-[20px] font-bold text-ink">Exporter</h2>
        <div className="flex flex-wrap gap-4">
          <a className="text-[17px] text-brand" href="/api/stats/export.csv">
            Exporter en CSV
          </a>
          <a className="text-[17px] text-brand" href="/api/stats/export.pdf">
            Exporter en PDF
          </a>
        </div>
      </section>
    </div>
  )
}

function Total({ icon, value, label }: { icon: 'box' | 'brick' | 'tag'; value: string; label: string }) {
  return (
    <div className="flex min-h-[130px] flex-col rounded-2xl bg-surface-raised p-3">
      <Icon name={icon} className="h-6 w-6 text-brand" />
      <p className="mt-2 text-[22px] font-bold leading-tight text-ink">{value}</p>
      <div className="flex-1" />
      <p className="text-[13px] text-ink-muted">{label}</p>
    </div>
  )
}

function Superlative({
  label,
  set,
  detail,
  onOpen,
}: {
  label: string
  set: SetRow | null
  detail: string
  onOpen: (path: string) => void
}) {
  if (!set) return null
  return (
    <button
      type="button"
      className="flex w-full items-center gap-2 border-b border-line py-2.5 text-left last:border-0"
      onClick={() => onOpen(`/set/${encodeURIComponent(set.setNum)}`)}
    >
      <span className="min-w-0 flex-1 text-[17px] text-ink">
        {label} : {set.setNum} — {set.name}
        {detail ? ` (${detail})` : ''}
      </span>
      <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-ink-faint" />
    </button>
  )
}
