import { useState } from 'react'
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
import type { BatchStatus, CollectionStats, SetRow } from '../api/types'
import Icon from '../components/Icon'
import ListConditionsSheet from '../components/ListConditionsSheet'
import { EmptyState, ErrorLabel, LoadingBlock, NavBar, ProgressBar, Spinner } from '../components/ui'
import { formatDate, formatEUR, formatEURCompact, formatNumber, formatPriceSources } from '../lib/format'

/** Beyond this the theme labels stop being readable on a phone; the rest is grouped as "Autres". */
const MAX_THEME_BARS = 10

export default function StatsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showListConditions, setShowListConditions] = useState(false)

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
    queryFn: () => api.get<BatchStatus>('/prices/batch/status'),
    refetchInterval: (q) => (q.state.data?.isRunning ? 2000 : false),
  })

  const cancelBatch = useMutation({
    mutationFn: () => api.post('/prices/batch/cancel'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['priceBatch'] }),
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

  // Recharts' defaults are a white tooltip and a light-grey hover band — both hardcoded, and both
  // glaring on a black page. Themed here once and reused by every chart on the screen.
  const tooltipStyle = {
    backgroundColor: 'rgb(var(--surface-raised))',
    border: '1px solid rgb(var(--line))',
    borderRadius: 12,
    color: 'rgb(var(--ink))',
    fontSize: 12,
  }
  const tooltipCursor = { fill: 'rgb(var(--ink) / 0.08)' }

  return (
    <div className="space-y-6 pb-10">
      <NavBar title="Statistiques" />

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
            <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: "rgb(var(--ink))" }} cursor={tooltipCursor} />
            <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" />
          </BarChart>
        </ResponsiveContainer>
      </section>

      {/* Horizontal bars against a category axis, as in the iOS `BarMark(x: sets, y: theme)`.
          Names above the bars (the previous attempt) wrapped onto two or three lines at phone
          width and collided with the bar above — the gutter is the readable place for them. */}
      <section className="card space-y-2">
        <h2 className="text-[20px] font-bold text-ink">Répartition par thème</h2>
        <ResponsiveContainer width="100%" height={topThemes.length * 30 + 36}>
          <BarChart
            data={topThemes}
            layout="vertical"
            margin={{ top: 4, right: 30, bottom: 4, left: 0 }}
            barCategoryGap={8}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: 'rgb(var(--ink-faint))' }} allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="themeName"
              width={104}
              interval={0}
              tickLine={false}
              axisLine={false}
              tick={<ThemeTick />}
            />
            <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: "rgb(var(--ink))" }} cursor={tooltipCursor} />
            <Bar dataKey="setCount" name="Sets" fill="rgb(var(--brand))" barSize={14} radius={[0, 4, 4, 0]}>
              {/* The count rides just past the end of its own bar: the short bars are otherwise
                  indistinguishable from each other. */}
              <LabelList
                dataKey="setCount"
                position="right"
                offset={6}
                style={{ fill: 'rgb(var(--ink-muted))', fontSize: 11 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </section>

      <section className="card space-y-2">
        {/* The refresh belongs to this card, not to the navigation bar: it re-reads the prices the
            total is made of, which is a different promise from "reload the page". While a batch
            runs the button gives way to its progress, as on iOS — a spinning icon that can't be
            pressed says less than "12 / 499". */}
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[20px] font-bold text-ink">Valeur estimée</h2>
          {batch.data?.isRunning ? (
            <span className="flex shrink-0 items-center gap-2 text-[13px] tabular-nums text-ink-muted">
              <Spinner className="h-3.5 w-3.5" />
              {batch.data.done} / {batch.data.total}
              {batch.data.currentSetNum ? ` · ${batch.data.currentSetNum}` : ''}
            </span>
          ) : (
            <button
              type="button"
              className="nav-circle h-9 w-9 shrink-0"
              onClick={() => refreshValue.mutate()}
              disabled={isFetching || refreshValue.isPending}
              aria-label="Actualiser tous les prix de la collection"
              title="Actualiser tous les prix de la collection"
            >
              <Icon name="refresh" className="h-4 w-4" />
            </button>
          )}
        </div>
        {/* The count alone ("38 / 499") gives no sense of how much is left; a serial price run is
            slow by design, so the bar is what makes a long wait legible rather than stalled. */}
        {batch.data?.isRunning && (
          <>
            <ProgressBar value={batch.data.done} total={batch.data.total} />
            {batch.data.pendingSources.length > 0 && (
              <p className="text-[13px] text-ink-muted">
                En attente de {formatPriceSources(batch.data.pendingSources)}
              </p>
            )}
            {batch.data.captchaRequiredSources.length > 0 && (
              <p className="text-[13px] text-amber-500">
                CAPTCHA requis : {formatPriceSources(batch.data.captchaRequiredSources)}.
              </p>
            )}
            {/* A run that looks stuck (a slow set, a stalled scrape) had no way out of this
                screen short of Réglages — the same "interrompre" here, progress kept. */}
            <button
              type="button"
              className="btn-ghost w-full justify-start px-0 text-left text-[13px]"
              onClick={() => cancelBatch.mutate()}
              disabled={cancelBatch.isPending || batch.data.cancelRequested}
            >
              {batch.data.cancelRequested
                ? 'Interruption en cours…'
                : 'Interrompre (la progression est conservée)'}
            </button>
          </>
        )}
        <p className="text-[28px] font-bold text-ink">{formatEUR(data.totalValueEur)}</p>
        {/* An estimated total is only honest next to its coverage. */}
        <p className="text-[13px] text-ink-muted">
          Basée sur {data.setsWithKnownPrice} / {data.setCount} sets ({data.pricedUnitCount} /{' '}
          {data.unitCount} exemplaires) dont le prix est connu
        </p>
        {/* When the figure was last actually re-read. A total with no date attached says nothing
            about whether it is today's market or last month's — so the line is always there, with
            the never-run case spelled out rather than hidden, exactly as on iOS. */}
        <p className="text-[13px] text-ink-muted">
          {batch.data?.lastCompletedAt
            ? `Dernière actualisation : ${formatDate(batch.data.lastCompletedAt)}`
            : 'Prix jamais actualisés'}
        </p>
        {(completeMissing.isError || refreshValue.isError || batch.data?.error) && (
          <ErrorLabel
            message={
              completeMissing.isError || refreshValue.isError
                ? ((completeMissing.error ?? refreshValue.error) as Error).message
                : batch.data?.error ?? 'Erreur inconnue'
            }
            className="text-[13px]"
          />
        )}
        {batch.data?.warning && (
          <p className="text-[13px] text-amber-500">{batch.data.warning}</p>
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
        {/* Opens the editor itself. It used to navigate to Ma collection, leaving the user to
            find the same sheet behind a tag button in that screen's navigation bar. */}
        <button
          type="button"
          className="btn-ghost w-full justify-between gap-2 px-0 text-left"
          onClick={() => setShowListConditions(true)}
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
              <Tooltip
                contentStyle={tooltipStyle}
                itemStyle={{ color: "rgb(var(--ink))" }}
                cursor={{ stroke: "rgb(var(--line))" }}
                formatter={(value: number) => formatEUR(value)}
              />
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

      <ListConditionsSheet
        open={showListConditions}
        onClose={() => setShowListConditions(false)}
      />
    </div>
  )
}

/**
 * A theme name in the chart's left gutter, truncated with an ellipsis rather than left to run off
 * the edge of the gutter — SVG text has no `text-overflow`, so an over-long name simply spilled
 * out of the card ("Speed Champions" rendered as "eed Champions").
 *
 * Twelve characters, not the ~15 the gutter looks wide enough for: the budget has to hold for the
 * widest glyphs, and "Speed Champion…" still overflowed where "Series 29 Mini…" fitted. It stays
 * long enough to keep "Series 29 minifigures" apart from "Series 24 minifigures".
 */
function ThemeTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const full = String(payload?.value ?? '')
  const label = full.length > 12 ? `${full.slice(0, 12)}…` : full
  return (
    <text
      x={x}
      y={y}
      dx={-6}
      dy={4}
      textAnchor="end"
      style={{ fill: 'rgb(var(--ink-muted))', fontSize: 11 }}
    >
      <title>{full}</title>
      {label}
    </text>
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
