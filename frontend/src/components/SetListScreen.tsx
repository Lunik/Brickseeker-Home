import { useMemo, useState, type ReactNode } from 'react'

import type { FilterState, SetRow as SetRowData, SortOption, StoreAvailability } from '../api/types'
import { filterAndSort, useFilterState } from '../hooks/useFilterState'
import FilterSheet from './FilterSheet'
import Icon from './Icon'
import SetRow from './SetRow'
import { ConfirmDialog, EmptyState, ErrorLabel, LoadingBlock, Sheet, Spinner } from './ui'

/**
 * The one browse screen. Collection, Historique, Liste cadeaux and Nouveaux sets are this screen
 * with different data; the minifig gallery is this screen with `renderItem` swapping the list for
 * a grid.
 *
 * Everything here — the persistent filter state, the trailing selection indicator, the bottom
 * action bar, the per-row context menu reusing the bulk code path — exists for a reason paid for
 * once in the iOS app. Copy this screen rather than assembling a new one.
 */

export interface BulkAction {
  key: string
  label: string
  destructive?: boolean
  /** Shown in a confirmation dialog before running. Omit for actions that need no confirmation. */
  confirm?: (count: number) => string
  run: (setNums: string[]) => Promise<void>
}

export interface SetListScreenProps {
  title: string
  rows: SetRowData[]
  isLoading?: boolean
  error?: string | null
  /** Namespaces the persistent filter state so one screen's filters never affect another's. */
  screenId: string
  defaultSort?: SortOption
  excludedSorts?: SortOption[]
  showOwnedFilter?: boolean
  showAvailabilityFilter?: boolean
  showLists?: boolean
  subtitleFor?: (row: SetRowData) => string | null
  bulkActions?: BulkAction[]
  onOpenSet?: (row: SetRowData, visible: SetRowData[]) => void
  emptyState?: ReactNode
  header?: ReactNode
  onRefresh?: () => void
  isRefreshing?: boolean
  /** Swaps the list for a custom presentation (the minifig gallery's grid). */
  renderItems?: (rows: SetRowData[]) => ReactNode
}

export default function SetListScreen({
  title,
  rows,
  isLoading = false,
  error = null,
  screenId,
  defaultSort = 'dateScanned',
  excludedSorts = [],
  showOwnedFilter = false,
  showAvailabilityFilter = true,
  showLists = false,
  subtitleFor,
  bulkActions = [],
  onOpenSet,
  emptyState,
  header,
  onRefresh,
  isRefreshing = false,
  renderItems,
}: SetListScreenProps) {
  const { filter, setFilter, reset, isActive } = useFilterState(screenId, defaultSort)
  const [showFilters, setShowFilters] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [menuFor, setMenuFor] = useState<SetRowData | null>(null)
  const [pending, setPending] = useState<{ action: BulkAction; targets: string[] } | null>(null)

  const visible = useMemo(
    () => filterAndSort(rows, { filter: filter as FilterState }),
    [rows, filter],
  )

  const themes = useMemo(
    () => [...new Set(rows.map((row) => row.themeName).filter(Boolean))].sort(),
    [rows],
  )
  const years = useMemo(
    () => [...new Set(rows.map((row) => row.year).filter((year) => year > 0))].sort((a, b) => b - a),
    [rows],
  )
  const lists = useMemo(
    () =>
      showLists
        ? [...new Set(rows.map((row) => row.currentListName).filter((name): name is string => !!name))].sort()
        : [],
    [rows, showLists],
  )
  const unknownAvailability = useMemo(
    () => rows.filter((row) => (row.availability as StoreAvailability) === 'unknown').length,
    [rows],
  )

  function toggle(setNum: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(setNum)) next.delete(setNum)
      else next.add(setNum)
      return next
    })
  }

  function leaveSelection() {
    setSelecting(false)
    setSelected(new Set())
  }

  async function run(action: BulkAction, targets: string[]) {
    setBusy(true)
    setActionError(null)
    try {
      await action.run(targets)
      leaveSelection()
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Action impossible')
    } finally {
      setBusy(false)
      setPending(null)
      setMenuFor(null)
    }
  }

  /** Both entry points funnel here, so a one-row context action and a bulk action can't diverge. */
  function request(action: BulkAction, targets: string[]) {
    if (!targets.length) return
    if (action.confirm) setPending({ action, targets })
    else void run(action, targets)
  }

  const allVisibleSelected = visible.length > 0 && visible.every((row) => selected.has(row.setNum))

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-ink">{title}</h1>
        <div className="flex items-center gap-1">
          {onRefresh && (
            <button
              type="button"
              className="btn-ghost px-2"
              onClick={onRefresh}
              disabled={isRefreshing}
              aria-label="Actualiser"
            >
              {isRefreshing ? <Spinner className="h-4 w-4" /> : <Icon name="refresh" />}
            </button>
          )}
          {bulkActions.length > 0 && rows.length > 0 && (
            <button
              type="button"
              className="btn-ghost px-2 text-sm"
              onClick={() => (selecting ? leaveSelection() : setSelecting(true))}
            >
              {selecting ? 'Terminé' : 'Sélectionner'}
            </button>
          )}
        </div>
      </div>

      {header}

      <div className="flex gap-2">
        <input
          type="search"
          className="input flex-1"
          placeholder="Rechercher un set…"
          value={filter.search}
          onChange={(event) => setFilter({ search: event.target.value })}
          aria-label="Rechercher"
        />
        <button
          type="button"
          className={isActive ? 'btn-primary px-3' : 'btn-secondary px-3'}
          onClick={() => setShowFilters(true)}
          aria-label={isActive ? 'Filtres (actifs)' : 'Filtres'}
        >
          <Icon name="filter" filled={isActive} />
        </button>
      </div>

      {actionError && <ErrorLabel message={actionError} />}

      {isLoading ? (
        <LoadingBlock />
      ) : error ? (
        <ErrorLabel message={error} />
      ) : visible.length === 0 ? (
        (emptyState ?? (
          <EmptyState
            icon={<Icon name="search" className="h-9 w-9" />}
            title={rows.length === 0 ? 'Rien à afficher' : 'Aucun résultat'}
            message={
              rows.length === 0
                ? undefined
                : 'Aucun set ne correspond à cette recherche ou à ces filtres.'
            }
            action={
              rows.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={reset}>
                  Réinitialiser les filtres
                </button>
              ) : undefined
            }
          />
        ))
      ) : renderItems ? (
        renderItems(visible)
      ) : (
        <>
          <p className="text-xs text-ink-faint">
            {visible.length} set{visible.length > 1 ? 's' : ''}
            {visible.length !== rows.length ? ` sur ${rows.length}` : ''}
          </p>
          <ul className="divide-y divide-line">
            {visible.map((row) => (
              <li key={row.setNum}>
                <SetRow
                  row={row}
                  subtitle={subtitleFor?.(row)}
                  selecting={selecting}
                  selected={selected.has(row.setNum)}
                  onClick={() => (selecting ? toggle(row.setNum) : onOpenSet?.(row, visible))}
                  onContextMenu={
                    selecting || bulkActions.length === 0
                      ? undefined
                      : (event) => {
                          event.preventDefault()
                          setMenuFor(row)
                        }
                  }
                />
              </li>
            ))}
          </ul>
        </>
      )}

      <FilterSheet
        open={showFilters}
        onClose={() => setShowFilters(false)}
        filter={filter}
        setFilter={setFilter}
        reset={reset}
        themes={themes as string[]}
        years={years}
        lists={lists}
        excludedSorts={excludedSorts}
        showOwnedFilter={showOwnedFilter}
        showAvailabilityFilter={showAvailabilityFilter}
        unknownAvailabilityCount={unknownAvailability}
      />

      {/* One row's context menu offers exactly the screen's bulk actions, applied to that row. */}
      <Sheet open={menuFor !== null} title={menuFor?.name ?? ''} onClose={() => setMenuFor(null)}>
        <div className="space-y-2">
          {bulkActions.map((action) => (
            <button
              key={action.key}
              type="button"
              className={action.destructive ? 'btn-danger w-full' : 'btn-secondary w-full'}
              disabled={busy}
              onClick={() => menuFor && request(action, [menuFor.setNum])}
            >
              {action.label}
            </button>
          ))}
        </div>
      </Sheet>

      {selecting && (
        // Bottom-anchored, never in the header: on iOS the search field hid a top bar, and the
        // same happens here on a phone keyboard.
        <div className="fixed inset-x-0 bottom-16 z-30 mx-auto w-full max-w-3xl border-t border-line bg-surface/95 px-4 py-2 backdrop-blur">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-ghost text-xs"
              onClick={() =>
                setSelected(allVisibleSelected ? new Set() : new Set(visible.map((row) => row.setNum)))
              }
            >
              {allVisibleSelected ? 'Tout désélectionner' : 'Tout sélectionner'}
            </button>
            <span className="text-xs text-ink-muted">{selected.size} sélectionné(s)</span>
            <span className="flex-1" />
            {busy && <Spinner className="h-4 w-4" />}
            {bulkActions.map((action) => (
              <button
                key={action.key}
                type="button"
                className={`${action.destructive ? 'btn-danger' : 'btn-secondary'} px-3 py-1.5 text-xs`}
                disabled={busy || selected.size === 0}
                onClick={() => request(action, [...selected])}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={pending?.action.label ?? ''}
        message={pending ? pending.action.confirm?.(pending.targets.length) : undefined}
        confirmLabel={pending?.action.label}
        destructive={pending?.action.destructive}
        onConfirm={() => pending && void run(pending.action, pending.targets)}
        onCancel={() => setPending(null)}
      />
    </div>
  )
}
