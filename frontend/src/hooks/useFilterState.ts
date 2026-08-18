/**
 * Search / filter / sort state shared by every browse screen, plus the one implementation of
 * "apply it to a list of rows".
 *
 * The state lives in a **module-level** store keyed by screen id, not in React state: each screen
 * is unmounted and rebuilt from scratch every time the user opens a set and comes back, and a
 * filter that resets on every dismiss is the single most infuriating thing this screen can do
 * (iOS holds these as process-lifetime singletons for exactly that reason). A full page reload
 * clears them, nothing else does.
 */

import { useCallback, useMemo, useSyncExternalStore } from 'react'

import type { FilterState, SortOption, StoreAvailability } from '../api/types'

/**
 * The direction each option reads most naturally in — newest/biggest first for the numeric and
 * date options, A→Z for the name. Switching sort resets the direction to this, so going from
 * "Nom" to "Année" doesn't silently carry an ascending choice over and show the oldest set first.
 */
export const SORT_DEFAULT_ASCENDING: Record<SortOption, boolean> = {
  dateScanned: false,
  dateAdded: false,
  year: false,
  name: true,
  partCount: false,
  price: false,
}

/** Menu order, not declaration order — the two date options belong next to each other. */
export const ALL_SORT_OPTIONS: SortOption[] = [
  'dateScanned',
  'dateAdded',
  'year',
  'name',
  'partCount',
  'price',
]

export const ALL_AVAILABILITIES: StoreAvailability[] = [
  'available',
  'outOfStock',
  'retired',
  'unknown',
]

function initialState(defaultSort: SortOption): FilterState {
  return {
    search: '',
    themeName: null,
    year: null,
    listName: null,
    ownedOnly: null,
    availability: null,
    sort: defaultSort,
    ascending: SORT_DEFAULT_ASCENDING[defaultSort],
  }
}

interface Store {
  state: FilterState
  /** The screen's own "nothing chosen yet" sort — `isActive` and `reset` compare against it, so a
   *  screen defaulting to something other than `dateScanned` doesn't permanently read as filtered. */
  defaultSort: SortOption
  listeners: Set<() => void>
}

const stores = new Map<string, Store>()

/** First call for a screen id decides its default sort; later calls reuse the live store. */
function storeFor(screenId: string, defaultSort: SortOption): Store {
  const existing = stores.get(screenId)
  if (existing) return existing
  const created: Store = { state: initialState(defaultSort), defaultSort, listeners: new Set() }
  stores.set(screenId, created)
  return created
}

export function isFilterActive(state: FilterState, defaultSort: SortOption): boolean {
  return (
    state.themeName !== null ||
    state.year !== null ||
    state.listName !== null ||
    state.ownedOnly !== null ||
    state.availability !== null ||
    state.sort !== defaultSort ||
    state.ascending !== SORT_DEFAULT_ASCENDING[state.sort]
  )
}

export interface FilterStateHandle {
  filter: FilterState
  /** Patch-style update. Setting `sort` without `ascending` also resets the direction. */
  setFilter: (patch: Partial<FilterState>) => void
  /** Clears filters and sort, keeping the search text — the two are cleared by separate
   *  affordances (the search field has its own clear button). */
  reset: () => void
  isActive: boolean
}

export function useFilterState(screenId: string, defaultSort: SortOption = 'dateScanned'): FilterStateHandle {
  const store = storeFor(screenId, defaultSort)

  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      const target = storeFor(screenId, defaultSort)
      target.listeners.add(onStoreChange)
      return () => {
        target.listeners.delete(onStoreChange)
      }
    },
    [screenId, defaultSort],
  )

  // Returns the same object until something actually changes, which is what useSyncExternalStore
  // needs to avoid an infinite re-render loop.
  const getSnapshot = useCallback(
    () => storeFor(screenId, defaultSort).state,
    [screenId, defaultSort],
  )

  const filter = useSyncExternalStore(subscribe, getSnapshot)

  const setFilter = useCallback(
    (patch: Partial<FilterState>) => {
      const target = storeFor(screenId, defaultSort)
      const next: FilterState = { ...target.state, ...patch }
      if (patch.sort !== undefined && patch.ascending === undefined) {
        next.ascending = SORT_DEFAULT_ASCENDING[patch.sort]
      }
      target.state = next
      for (const listener of target.listeners) listener()
    },
    [screenId, defaultSort],
  )

  const reset = useCallback(() => {
    const target = storeFor(screenId, defaultSort)
    target.state = { ...initialState(target.defaultSort), search: target.state.search }
    for (const listener of target.listeners) listener()
  }, [screenId, defaultSort])

  return useMemo(
    () => ({ filter, setFilter, reset, isActive: isFilterActive(filter, store.defaultSort) }),
    [filter, setFilter, reset, store.defaultSort],
  )
}

/* -------------------------------------------------------------------------- */
/*  Applying the filter                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The shape `filterAndSort` (and the shared list screen) can work with. `SetRow` satisfies it as
 * is; a screen browsing something else (the minifig catalogue, a search result) maps its own rows
 * into this shape or overrides the accessors below.
 */
export interface BrowsableRow {
  setNum: string
  name: string
  year: number
  numParts: number
  themeName?: string | null
  currentListName?: string | null
  isInCollection?: boolean
  availability?: StoreAvailability
  lastScannedAt?: string | null
  /** When this install first saw the entry in a catalogue snapshot — `dateAdded` sort. */
  firstSeenAt?: string | null
  resolvedPrice?: number | null
  setImgUrl?: string | null
  quantity?: number
  isInWishlist?: boolean
  hasPriceAlert?: boolean
  priceLabel?: string | null
  priceCondition?: string | null
}

export interface FilterAndSortOptions<T> {
  filter: FilterState
  /** Resolved display **name** for the row's theme. Rebrickable's theme table is hierarchical and
   *  distinct ids share a name, so matching by id splits one theme into two silently. */
  themeName?: (row: T) => string
  price?: (row: T) => number | null
  owned?: (row: T) => boolean
  listName?: (row: T) => string | null
  availability?: (row: T) => StoreAvailability
  scannedAt?: (row: T) => string | number | null
  addedAt?: (row: T) => string | number | null
}

function toTime(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null
  const time = typeof value === 'number' ? value : Date.parse(value)
  return Number.isNaN(time) ? null : time
}

/** Rows with nothing to compare sort last in **both** directions — there is no honest place to put
 *  a set with no price among sets that have one. */
function compareNullable(a: number | null, b: number | null, ascending: boolean): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return ascending ? a - b : b - a
}

export function filterAndSort<T extends BrowsableRow>(
  rows: readonly T[],
  options: FilterAndSortOptions<T>,
): T[] {
  const { filter } = options
  const themeNameOf = options.themeName ?? ((row: T) => row.themeName ?? '')
  const priceOf = options.price ?? ((row: T) => row.resolvedPrice ?? null)
  const ownedOf = options.owned ?? ((row: T) => row.isInCollection === true)
  const listNameOf = options.listName ?? ((row: T) => row.currentListName ?? null)
  const availabilityOf = options.availability ?? ((row: T) => row.availability ?? 'unknown')
  const scannedAtOf = options.scannedAt ?? ((row: T) => row.lastScannedAt ?? null)
  const addedAtOf = options.addedAt ?? ((row: T) => row.firstSeenAt ?? null)

  let result = [...rows]

  const needle = filter.search.trim().toLocaleLowerCase('fr')
  if (needle) {
    result = result.filter(
      (row) =>
        row.name.toLocaleLowerCase('fr').includes(needle) ||
        row.setNum.toLocaleLowerCase('fr').includes(needle),
    )
  }
  if (filter.themeName !== null) {
    result = result.filter((row) => themeNameOf(row) === filter.themeName)
  }
  if (filter.year !== null) {
    result = result.filter((row) => row.year === filter.year)
  }
  if (filter.listName !== null) {
    result = result.filter((row) => listNameOf(row) === filter.listName)
  }
  if (filter.ownedOnly !== null) {
    result = result.filter((row) => ownedOf(row) === filter.ownedOnly)
  }
  if (filter.availability !== null) {
    // A set nobody ever fetched a lego.com price for resolves to `unknown`, so it matches only the
    // explicit "Inconnue" choice and never leaks into one of the three real store states.
    result = result.filter((row) => availabilityOf(row) === filter.availability)
  }

  const ascending = filter.ascending
  switch (filter.sort) {
    case 'name':
      result.sort((a, b) => {
        const order = a.name.localeCompare(b.name, 'fr', { sensitivity: 'base' })
        return ascending ? order : -order
      })
      break
    case 'year':
      // `year` is the finest-grained date Rebrickable exposes, so hundreds of rows tie on it; the
      // setNum tiebreak isn't a chronological claim, only a deterministic one, so the list stops
      // reshuffling ties between renders for no visible reason.
      result.sort((a, b) => {
        if (a.year !== b.year) return ascending ? a.year - b.year : b.year - a.year
        return ascending ? a.setNum.localeCompare(b.setNum) : b.setNum.localeCompare(a.setNum)
      })
      break
    case 'partCount':
      result.sort((a, b) => (ascending ? a.numParts - b.numParts : b.numParts - a.numParts))
      break
    case 'price': {
      // Pre-resolve once: the accessor may walk a price index, and sorting would otherwise call it
      // O(n log n) times.
      const priced = result.map((row) => ({ row, value: priceOf(row) }))
      priced.sort((a, b) => compareNullable(a.value, b.value, ascending))
      result = priced.map((entry) => entry.row)
      break
    }
    case 'dateScanned': {
      const dated = result.map((row) => ({ row, value: toTime(scannedAtOf(row)) }))
      dated.sort((a, b) => compareNullable(a.value, b.value, ascending))
      result = dated.map((entry) => entry.row)
      break
    }
    case 'dateAdded': {
      const dated = result.map((row) => ({ row, value: toTime(addedAtOf(row)) }))
      dated.sort((a, b) => compareNullable(a.value, b.value, ascending))
      result = dated.map((entry) => entry.row)
      break
    }
  }

  return result
}
