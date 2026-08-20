import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import type { FilterState, SetRow as SetRowData, SortOption, StoreAvailability } from '../api/types'
import { filterAndSort, useFilterState } from '../hooks/useFilterState'
import FilterSheet from './FilterSheet'
import Icon from './Icon'
import SelectionBar, { ActionSheet, type SelectionAction } from './SelectionBar'
import SetRow from './SetRow'
import { ConfirmDialog, EmptyState, ErrorLabel, LoadingBlock, NavBar, Spinner } from './ui'

/**
 * The one browse screen. Collection, Historique, Liste cadeaux and Nouveaux sets are this screen
 * with different data; the minifig gallery is this screen with `renderItems` swapping the list for
 * a grid.
 *
 * Everything here — the persistent filter state, the trailing selection indicator, the floating
 * select button, the per-row context menu reusing the bulk code path — exists for a reason paid
 * for once in the iOS app. Copy this screen rather than assembling a new one.
 */

/** Rows mounted per page as the list is scrolled. */
const PAGE = 40

/** The actions a screen offers on a selection — and, unchanged, on one row's context menu. */
export type BulkAction = SelectionAction

/**
 * What a custom renderer needs to behave like the rows it replaces.
 *
 * `activate` exists so no caller has to re-derive "tap toggles while selecting, opens otherwise":
 * the minifig grid did re-derive it, got it wrong, and opened a minifig instead of ticking it —
 * while keeping a private selection set the "Actions (N)" count knew nothing about.
 */
export interface RenderSelection {
  selecting: boolean
  isSelected: (setNum: string) => boolean
  /** The row's own tap. */
  activate: (row: SetRowData) => void
  /** Long-press / right-click, which opens that row's action menu. */
  openMenu: (row: SetRowData) => void
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
  searchPlaceholder?: string
  subtitleFor?: (row: SetRowData) => string | null
  bulkActions?: BulkAction[]
  onOpenSet?: (row: SetRowData, visible: SetRowData[]) => void
  emptyState?: ReactNode
  /** Extra pill buttons for the navigation bar, left of the filter button. */
  navActions?: ReactNode
  header?: ReactNode
  onRefresh?: () => void
  isRefreshing?: boolean
  renderItems?: (rows: SetRowData[], selection: RenderSelection) => ReactNode
  /** The caller already applied `filter` server-side; skip the client-side pass. */
  serverFiltered?: boolean
  /** What the trailing count caption calls one row — the minifig gallery isn't sets. */
  itemNoun?: string
  /**
   * Theme/year choices for the filter sheet, computed over the screen's whole scope.
   *
   * Required on a `serverFiltered` screen: `rows` there is one page, and deriving the dropdown
   * from it offers only whatever theme/year happened to land on that page — picking anything else
   * silently returned nothing (#finding-10). Omit on a client-filtered screen, where `rows` really
   * is everything and deriving from it is correct.
   */
  themeOptions?: string[]
  yearOptions?: number[]
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
  searchPlaceholder = 'Nom ou numéro de set',
  subtitleFor,
  bulkActions = [],
  onOpenSet,
  emptyState,
  navActions,
  header,
  onRefresh,
  isRefreshing = false,
  renderItems,
  serverFiltered = false,
  itemNoun = 'set',
  themeOptions,
  yearOptions,
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
    () => (serverFiltered ? rows : filterAndSort(rows, { filter: filter as FilterState })),
    [rows, filter, serverFiltered],
  )

  const themes = useMemo(
    () => themeOptions ?? [...new Set(rows.map((row) => row.themeName).filter(Boolean))].sort(),
    [rows, themeOptions],
  )
  const years = useMemo(
    () =>
      yearOptions ??
      [...new Set(rows.map((row) => row.year).filter((year) => year > 0))].sort((a, b) => b - a),
    [rows, yearOptions],
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

  // Rows are mounted in pages as the user reaches the bottom. A 499-set collection otherwise
  // mounts 499 rows and 499 <img> in one go, which is what makes the first paint crawl.
  const [renderLimit, setRenderLimit] = useState(PAGE)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setRenderLimit(PAGE)
  }, [rows, filter])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setRenderLimit((current) => Math.min(current + PAGE, visible.length))
        }
      },
      // Start the next page before the sentinel is actually on screen, so scrolling stays smooth.
      { rootMargin: '600px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [visible.length])

  const rendered = useMemo(() => visible.slice(0, renderLimit), [visible, renderLimit])

  const allVisibleSelected = visible.length > 0 && visible.every((row) => selected.has(row.setNum))

  return (
    <div className="space-y-3 pb-24">
      <NavBar
        title={title}
        actions={
          <>
            {navActions}
            {onRefresh && (
              <button
                type="button"
                className="nav-circle"
                onClick={onRefresh}
                disabled={isRefreshing}
                aria-label="Actualiser"
              >
                {isRefreshing ? <Spinner className="h-5 w-5" /> : <Icon name="refresh" />}
              </button>
            )}
            <button
              type="button"
              className="nav-circle"
              onClick={() => setShowFilters(true)}
              aria-label={isActive ? 'Filtres (actifs)' : 'Filtres'}
            >
              <Icon name="filter" filled={isActive} />
            </button>
          </>
        }
      />

      <div className="relative">
        <Icon name="search" className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-faint" />
        <input
          type="search"
          className="search-field"
          placeholder={searchPlaceholder}
          value={filter.search}
          onChange={(event) => setFilter({ search: event.target.value })}
          aria-label="Rechercher"
        />
      </div>

      {header}
      {actionError && <ErrorLabel message={actionError} />}

      {isLoading ? (
        <LoadingBlock />
      ) : error && rows.length === 0 ? (
        // A background refetch failing while a persisted list is already on screen (offline, or a
        // slow LAN) must not hide it behind a full-page error — the offline banner already says
        // "expect stale data" without repeating it five times across every list screen.
        <ErrorLabel message={error} />
      ) : visible.length === 0 ? (
        // The caller's empty state answers "there is nothing here"; once a search or filter is
        // active the honest answer is "nothing matches", with a way to clear it.
        (rows.length > 0 || isActive || filter.search ? null : emptyState) ?? (
          <EmptyState
            icon={<Icon name="search" className="h-10 w-10" />}
            title={rows.length === 0 ? 'Rien à afficher' : 'Aucun résultat'}
            message={
              rows.length === 0 ? undefined : 'Aucun set ne correspond à cette recherche ou à ces filtres.'
            }
            action={
              rows.length > 0 ? (
                <button type="button" className="btn-secondary" onClick={reset}>
                  Réinitialiser les filtres
                </button>
              ) : undefined
            }
          />
        )
      ) : (
        <>
          {renderItems ? (
            renderItems(rendered, {
              selecting,
              isSelected: (setNum) => selected.has(setNum),
              activate: (row) => (selecting ? toggle(row.setNum) : onOpenSet?.(row, visible)),
              openMenu: (row) => {
                if (!selecting && bulkActions.length > 0) setMenuFor(row)
              },
            })
          ) : (
            // One grouped card holding every row, dividers inset past the thumbnail.
            <ul className="list-card">
              {rendered.map((row, index) => (
                <li
                  key={row.setNum}
                  className={index > 0 ? 'border-t border-line ml-[76px] pl-0' : ''}
                >
                  <div className={index > 0 ? '-ml-[76px]' : ''}>
                    <SetRow
                      row={row}
                      subtitle={subtitleFor?.(row)}
                      selecting={selecting}
                      selected={selected.has(row.setNum)}
                      onClick={() => (selecting ? toggle(row.setNum) : onOpenSet?.(row, visible))}
                      onQuickAction={selecting || bulkActions.length === 0 ? undefined : setMenuFor}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {/* The observer target: reaching it mounts the next page. Both branches above need it —
              renderItems screens (the minifig grid) page exactly like the list does. */}
          <div ref={sentinelRef} aria-hidden="true" />
          <p className="px-1 text-[13px] text-ink-faint">
            {visible.length} {itemNoun}
            {visible.length > 1 ? 's' : ''}
            {visible.length !== rows.length ? ` sur ${rows.length}` : ''}
            {renderLimit < visible.length ? ` · ${renderLimit} affichés` : ''}
          </p>
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
      {/* One row's actions and a selection's actions are the same list, rendered by the same
          component — the iOS screens keep those two in lockstep for the same reason. */}
      <ActionSheet
        open={menuFor !== null}
        title={menuFor?.name ?? ''}
        actions={bulkActions}
        busy={busy}
        onClose={() => setMenuFor(null)}
        onPick={(action) => {
          const target = menuFor
          setMenuFor(null)
          if (target) request(action, [target.setNum])
        }}
      />

      {/* Selection is entered from a floating button, and its controls sit at the bottom — a
          top-bar control would be hidden by the keyboard while the search field is focused. */}
      {bulkActions.length > 0 && rows.length > 0 && !selecting && (
        <button
          type="button"
          className="fixed bottom-8 right-5 z-20 flex h-14 w-14 items-center justify-center rounded-full bg-surface-raised text-brand shadow-lg"
          onClick={() => setSelecting(true)}
          aria-label="Sélectionner des sets"
        >
          <Icon name="checklist" className="h-6 w-6" />
        </button>
      )}

      {selecting && (
        <SelectionBar
          count={selected.size}
          total={visible.length}
          allSelected={allVisibleSelected}
          busy={busy}
          actions={bulkActions}
          onToggleAll={() =>
            setSelected(allVisibleSelected ? new Set() : new Set(visible.map((row) => row.setNum)))
          }
          onDone={leaveSelection}
          onRun={(action) => request(action, [...selected])}
        />
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
