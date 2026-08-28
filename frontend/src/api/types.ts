/**
 * Wire types. Mirrors the backend's camelCase JSON (see docs/contract.md); the names match the
 * iOS models the whole app is ported from, so `setNum`/`numParts` read the same on both sides.
 */

export type ListCondition = 'newSet' | 'used'
export type PriceSourceKey = 'bricklinkUsed' | 'bricklinkNew' | 'amazon' | 'cdiscount'
export type StoreAvailability = 'available' | 'outOfStock' | 'retired' | 'unknown'
export type NonSetKind = 'merchandise' | 'book' | 'exclusive' | 'catalogArtifact'

export interface LegoSet {
  setNum: string
  name: string
  year: number
  themeId: number
  numParts: number
  setImgUrl: string | null
  setUrl: string | null
}

export interface PriceQuote {
  source: PriceSourceKey
  amount: number
  currency: string
  sourceUrl: string | null
  fetchedAt: string | null
  minAmount: number | null
  maxAmount: number | null
  lotCount: number | null
  /** The average rests on ≤2 lots — one atypical sale *is* the quote. */
  isThinSample: boolean
  isStale: boolean
}

export interface Valuation {
  currentValueEur: number | null
  basisEur: number | null
  basis: 'paid' | 'retail' | 'unknown'
  valuedCondition: ListCondition | null
  growthPercent: number | null
  asOf: string | null
  isStale: boolean
}

/** A list row. `priceCondition` is what the amount actually represents, which is not always the
 *  list's nominal condition — a `used` list with no BrickLink used quote is priced off the new
 *  chain, and the row says so rather than mislabelling it. */
export interface SetRow {
  setNum: string
  name: string
  year: number
  themeId: number
  themeName: string
  numParts: number
  setImgUrl: string | null
  quantity: number
  isInCollection: boolean
  isInWishlist: boolean
  hasPriceAlert: boolean
  wasScanned: boolean
  lastScannedAt: string | null
  currentListId: number | null
  currentListName: string | null
  storePriceEur: number | null
  availability: StoreAvailability
  resolvedPrice: number | null
  priceCondition: ListCondition | null
  priceLabel: string | null
  dealPercent: number | null
  dealSource: PriceSourceKey | null
}

export interface ScanEvent {
  id: number
  setNum: string
  scannedAt: string
  latitude: number | null
  longitude: number | null
  placeName: string | null
  priceSeenEur: number | null
}

export interface PriceAlert {
  id: number
  setNum: string
  condition: ListCondition
  setName: string
  setImgUrl: string | null
  thresholdEur: number | null
  discountPercent: number | null
  referencePriceEur: number | null
  referenceSourceName: string | null
  effectiveThresholdEur: number | null
  isEnabled: boolean
  lastObservedPriceEur: number | null
  lastNotifiedAt: string | null
  createdAt: string
}

export interface PriceHistoryPoint {
  source: string
  sourceName: string
  amount: number
  fetchedAt: string
}

export interface SoldSale {
  source: PriceSourceKey
  unitAmount: number
  quantity: number
  orderedAt: string
}

export interface SetDetail {
  set: LegoSet
  themeName: string
  isInCollection: boolean
  currentListId: number | null
  currentListName: string | null
  listCondition: ListCondition | null
  quantity: number
  isInWishlist: boolean
  storePriceEur: number | null
  storeCurrency: string | null
  availability: StoreAvailability
  storePriceFetchedAt: string | null
  quotes: PriceQuote[]
  valuation: Valuation
  paidPriceEur: number | null
  priceHistory: PriceHistoryPoint[]
  soldListings: SoldSale[]
  scanEvents: ScanEvent[]
  /** The scan where the cheapest in-store price was seen — "where was it cheapest?", a different
   *  question from the purchase-price seed, which follows the most *recent* priced scan. */
  bestPriceScanId: number | null
  alerts: PriceAlert[]
  nonSetKind: NonSetKind | null
  storeUrl: string | null
  instructionsUrl: string | null
  isMinifig: boolean
  isOfflineResult: boolean
  /** `prices_fetched_at` was more than 7 days old (or never set), so the backend already kicked
   *  off a background refresh for this item — see `SetDetailPage`'s one-shot delayed refetch. */
  pricesRefreshing: boolean
}

export type ResolveStatus = 'found' | 'ambiguous' | 'notFound' | 'offline'

export interface ResolveResult {
  status: ResolveStatus
  set: LegoSet | null
  candidates: LegoSet[]
  isFromCache: boolean
  /** The `ScanEvent` just recorded, when the lookup counted as a scan. */
  scanEventId?: number | null
}

export interface SetListInfo {
  id: number
  name: string
  numSets: number
  condition: ListCondition
}

export interface CollectionPayload {
  sets: SetRow[]
  lists: SetListInfo[]
  lastSyncedAt: string | null
  isLinked: boolean
}

export interface ThemeBreakdown {
  themeId: number
  themeName: string
  setCount: number
  partCount: number
}

export interface YearBreakdown {
  bucketStart: number
  label: string
  setCount: number
}

export interface ValueSnapshot {
  dayKey: string
  totalValueEur: number
  setsCount: number
  unitsCount: number
  pricedSetsCount: number
  coverage: number
  /** Below 0.8 the reading is real but under-states the collection; the chart greys it rather
   *  than plotting a crash that never happened. */
  isReliable: boolean
}

export interface CollectionStats {
  setCount: number
  unitCount: number
  partCount: number
  themeCount: number
  themeBreakdown: ThemeBreakdown[]
  yearBreakdown: YearBreakdown[]
  totalValueEur: number
  setsWithKnownPrice: number
  pricedUnitCount: number
  /** Sets a "compléter les prix manquants" run would actually process. */
  completablePriceCount: number
  mostExpensiveSet: SetRow | null
  mostExpensiveSetPriceEur: number | null
  oldestSet: SetRow | null
  largestSet: SetRow | null
  valueSnapshots: ValueSnapshot[]
}

export interface Preferences {
  'appTheme.brandColor': 'red' | 'yellow' | 'blue'
  'appTheme.appearanceMode': 'system' | 'light' | 'dark'
  'appTheme.preferredPricePerPart': number
  hide_wearables_enabled: boolean
  scan_location_enabled: boolean
  hasSeenOnboarding: boolean
  hasSeenBatchModeIntro: boolean
  'backgroundRefresh.enabled': boolean
  'notifications.pushEnabled': boolean
  [key: string]: unknown
}

export interface CredentialStatus {
  rebrickableApiKey: boolean
  rebrickableLinked: boolean
  bricksetApiKey: boolean
  bricksetLinked: boolean
  bricklink: boolean
}

export interface CatalogEntryStatus {
  downloadedAt: string | null
  rowCount: number
  /** Live progress while a download runs, persisted server-side so the UI can poll it. */
  status: { state?: string; progress?: number; message?: string } | null
}

export type CatalogName = 'sets' | 'themes' | 'minifigs'

export interface CatalogStatus {
  sets: CatalogEntryStatus
  themes: CatalogEntryStatus
  minifigs: CatalogEntryStatus
  /** MIN(firstSeenAt) — a set is genuinely *new* only when its own firstSeenAt is after this. */
  initialSyncAt: string | null
}

/**
 * `GET /prices/{setNum}` — the cached prices for one set, without triggering any scraping.
 *
 * `percentVsStore` is the ±% against the lego.com price, per source, computed server-side so that
 * every screen shows the same number instead of each re-deriving it.
 */
export interface SetPrices {
  setNum: string
  quotes: PriceQuote[]
  storePriceEur: number | null
  storeCurrency: string | null
  availability: StoreAvailability
  storePriceFetchedAt: string | null
  valuation: Valuation
  percentVsStore: Partial<Record<PriceSourceKey, number>>
}

export interface BatchStatus {
  isRunning: boolean
  done: number
  total: number
  currentSetNum: string | null
  mode: string | null
  lastCompletedAt: string | null
}

export interface SettingsPayload {
  preferences: Preferences
  credentials: CredentialStatus
  catalog: CatalogStatus
  priceUpdate: BatchStatus
}

export interface AppNotification {
  id: number
  kind: 'priceAlert' | 'batchComplete' | 'catalog'
  title: string
  body: string
  setNum: string | null
  createdAt: string
  readAt: string | null
}

export interface MinifigRow {
  figNum: string
  name: string
  numParts: number
  imgUrl: string | null
  themeId: number | null
  themeName: string | null
  year: number | null
  ownedQuantity: number
  resolvedPrice: number | null
  containingSetNums: string[]
}

export interface DealComparison {
  label: string
  referenceAmount: number
  differenceAmount: number
  percent: number
  fetchedAt: string | null
}

export interface DealVerdictResult {
  verdict: 'good' | 'fair' | 'bad'
  emoji: string
  label: string
  comparisons: DealComparison[]
}

export type SortOption = 'dateScanned' | 'year' | 'name' | 'partCount' | 'price' | 'dateAdded' | 'deal'

export interface FilterState {
  search: string
  themeName: string | null
  year: number | null
  listName: string | null
  ownedOnly: boolean | null
  availability: StoreAvailability | null
  sort: SortOption
  ascending: boolean
}
